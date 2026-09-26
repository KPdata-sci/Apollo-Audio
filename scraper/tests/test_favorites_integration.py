"""Write-based integration checks for the favorites feature, against the real
Postgres warehouse at APOLLO_WAREHOUSE_DSN. Kept separate from
test_warehouse_integration.py, which is deliberately read-only against a
database that may hold real scraped data — these tests need to write, so each
one creates its own disposable track row up front and deletes it afterward
(via a fixture's finally-equivalent teardown, so a failed assertion still
cleans up) rather than touching anything a real scrape produced."""

from datetime import datetime, timezone

import psycopg
import pytest

from app import warehouse
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


@pytest.fixture
def fixture_track_id():
    track_id = _insert_fixture_track("round-trip")
    try:
        yield track_id
    finally:
        _delete_track(track_id)


def test_favorite_then_unfavorite_round_trips(fixture_track_id):
    assert warehouse.add_favorite(fixture_track_id) is True
    rows, _ = warehouse.list_tracks(favorited_only=True, limit=200)
    assert any(r["id"] == fixture_track_id and r["favorited"] for r in rows)

    assert warehouse.remove_favorite(fixture_track_id) is True
    rows, _ = warehouse.list_tracks(favorited_only=True, limit=200)
    assert all(r["id"] != fixture_track_id for r in rows)


def test_favoriting_twice_is_idempotent(fixture_track_id):
    assert warehouse.add_favorite(fixture_track_id) is True
    assert warehouse.add_favorite(fixture_track_id) is True  # no IntegrityError on the second call
    _, total = warehouse.list_tracks(favorited_only=True, source_url=_FIXTURE_SOURCE_URL, limit=200)
    assert total == 1


def test_unfavoriting_twice_is_idempotent(fixture_track_id):
    assert warehouse.add_favorite(fixture_track_id) is True
    assert warehouse.remove_favorite(fixture_track_id) is True
    assert warehouse.remove_favorite(fixture_track_id) is True  # already gone — still not an error


def test_favorite_actions_404_shape_for_unknown_track_id():
    # id 0 can never exist (SERIAL starts at 1) — no fixture needed.
    assert warehouse.add_favorite(0) is False
    assert warehouse.remove_favorite(0) is False


def test_deleting_a_favorited_track_cascades_the_favorite():
    # The favorites row must not outlive its track (ON DELETE CASCADE) or a
    # stale track_id would sit in `favorites` referencing nothing.
    track_id = _insert_fixture_track("cascade")
    warehouse.add_favorite(track_id)

    _delete_track(track_id)

    with psycopg.connect(settings.warehouse_dsn) as conn:
        remaining = conn.execute("SELECT 1 FROM favorites WHERE track_id = %s", [track_id]).fetchone()
    assert remaining is None
