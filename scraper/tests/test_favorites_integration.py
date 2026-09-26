"""Write-based integration checks for the favorites feature, against the real
Postgres warehouse at APOLLO_WAREHOUSE_DSN. Kept separate from
test_warehouse_integration.py, which is deliberately read-only against a
database that may hold real scraped data — these tests need to write, so each
one creates its own disposable track/user rows up front and deletes them
afterward (via a fixture's teardown, so a failed assertion still cleans up)
rather than touching anything a real scrape or a real account produced."""

import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from app import warehouse
from app.auth import hash_password
from app.settings import settings


def _db_reachable() -> bool:
    try:
        with psycopg.connect(settings.warehouse_dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1 FROM tracks LIMIT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "not available here"
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(), reason="warehouse at APOLLO_WAREHOUSE_DSN not reachable"
)

# Distinct from any URL a real scrape would ever produce, so these rows are
# unmistakably test fixtures if cleanup is ever interrupted mid-run.
_FIXTURE_SOURCE_URL = "https://soundcloud.com/apollo-test-fixture/sets/favorites-test"


def _insert_fixture_track(suffix: str) -> int:
    url = f"{_FIXTURE_SOURCE_URL}#{suffix}-{datetime.now(timezone.utc).timestamp()}"
    warehouse.load_tracks(
        [{"artist": "Apollo Test Fixture", "title": "Fixture Track", "url": url}],
        source_url=_FIXTURE_SOURCE_URL,
        lake_object_key="raw/soundcloud/test-fixture.json",
        scraped_at=datetime.now(timezone.utc),
    )
    with psycopg.connect(settings.warehouse_dsn) as conn:
        return conn.execute("SELECT id FROM tracks WHERE url = %s", [url]).fetchone()[0]


def _delete_track(track_id: int) -> None:
    with psycopg.connect(settings.warehouse_dsn) as conn:
        conn.execute("DELETE FROM tracks WHERE id = %s", [track_id])
        conn.commit()


def _insert_fixture_user() -> int:
    # A random, never-colliding username, so parallel/repeated runs never
    # trip the UNIQUE constraint against a previous run's leftover.
    username = f"apollo-test-fixture-{uuid.uuid4().hex[:12]}"
    return warehouse.insert_user(username, hash_password("not-a-real-password"))


def _delete_user(user_id: int) -> None:
    with psycopg.connect(settings.warehouse_dsn) as conn:
        conn.execute("DELETE FROM users WHERE id = %s", [user_id])  # cascades to favorites
        conn.commit()


@pytest.fixture
def fixture_track_id():
    track_id = _insert_fixture_track("round-trip")
    try:
        yield track_id
    finally:
        _delete_track(track_id)


@pytest.fixture
def fixture_user_id():
    user_id = _insert_fixture_user()
    try:
        yield user_id
    finally:
        _delete_user(user_id)


def test_favorite_then_unfavorite_round_trips(fixture_user_id, fixture_track_id):
    assert warehouse.add_favorite(fixture_user_id, fixture_track_id) is True
    rows, _ = warehouse.list_tracks(favorited_only=True, current_user_id=fixture_user_id, limit=200)
    assert any(r["id"] == fixture_track_id and r["favorited"] for r in rows)

    assert warehouse.remove_favorite(fixture_user_id, fixture_track_id) is True
    rows, _ = warehouse.list_tracks(favorited_only=True, current_user_id=fixture_user_id, limit=200)
    assert all(r["id"] != fixture_track_id for r in rows)


def test_favoriting_twice_is_idempotent(fixture_user_id, fixture_track_id):
    assert warehouse.add_favorite(fixture_user_id, fixture_track_id) is True
    assert warehouse.add_favorite(fixture_user_id, fixture_track_id) is True  # no IntegrityError on the second call
    _, total = warehouse.list_tracks(
        favorited_only=True, current_user_id=fixture_user_id, source_url=_FIXTURE_SOURCE_URL, limit=200
    )
    assert total == 1


def test_unfavoriting_twice_is_idempotent(fixture_user_id, fixture_track_id):
    assert warehouse.add_favorite(fixture_user_id, fixture_track_id) is True
    assert warehouse.remove_favorite(fixture_user_id, fixture_track_id) is True
    assert warehouse.remove_favorite(fixture_user_id, fixture_track_id) is True  # already gone — still not an error


def test_favorite_actions_404_shape_for_unknown_track_id(fixture_user_id):
    # track id 0 can never exist (SERIAL starts at 1) — no track fixture needed.
    assert warehouse.add_favorite(fixture_user_id, 0) is False
    assert warehouse.remove_favorite(fixture_user_id, 0) is False


def test_deleting_a_favorited_track_cascades_the_favorite(fixture_user_id):
    # The favorites row must not outlive its track (ON DELETE CASCADE) or a
    # stale track_id would sit in `favorites` referencing nothing.
    track_id = _insert_fixture_track("cascade")
    warehouse.add_favorite(fixture_user_id, track_id)

    _delete_track(track_id)

    with psycopg.connect(settings.warehouse_dsn) as conn:
        remaining = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = %s AND track_id = %s", [fixture_user_id, track_id]
        ).fetchone()
    assert remaining is None


def test_two_users_favorites_are_isolated(fixture_track_id):
    # The whole point of making this per-user: my favoriting a track must
    # never make it show up as favorited for someone else.
    user_a = _insert_fixture_user()
    user_b = _insert_fixture_user()
    try:
        assert warehouse.add_favorite(user_a, fixture_track_id) is True

        rows_a, _ = warehouse.list_tracks(favorited_only=True, current_user_id=user_a, limit=200)
        assert any(r["id"] == fixture_track_id for r in rows_a)

        rows_b, _ = warehouse.list_tracks(favorited_only=True, current_user_id=user_b, limit=200)
        assert all(r["id"] != fixture_track_id for r in rows_b)

        # Browsing without favorited_only still shows the track to user B —
        # just never marked favorited on their behalf.
        all_rows_b, _ = warehouse.list_tracks(current_user_id=user_b, source_url=_FIXTURE_SOURCE_URL, limit=200)
        track_for_b = next(r for r in all_rows_b if r["id"] == fixture_track_id)
        assert track_for_b["favorited"] is False
    finally:
        _delete_user(user_a)
        _delete_user(user_b)


def test_deleting_a_user_cascades_their_favorites(fixture_track_id):
    user_id = _insert_fixture_user()
    warehouse.add_favorite(user_id, fixture_track_id)

    _delete_user(user_id)

    with psycopg.connect(settings.warehouse_dsn) as conn:
        remaining = conn.execute(
            "SELECT 1 FROM favorites WHERE track_id = %s", [fixture_track_id]
        ).fetchone()
    assert remaining is None
