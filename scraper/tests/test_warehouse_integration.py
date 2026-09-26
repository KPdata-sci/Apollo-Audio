"""Read-only integration checks against the real Postgres warehouse at
APOLLO_WAREHOUSE_DSN. Skipped automatically when that database isn't
reachable (e.g. the plain unit-test run with no compose network). These tests
never write — the database they point at may hold real scraped data."""

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


def _all_rows(sort: str, page_size: int = 25, **filters) -> tuple[list[dict], int]:
    out: list[dict] = []
    offset = 0
    total = None
    while True:
        rows, total = warehouse.list_tracks(sort=sort, limit=page_size, offset=offset, **filters)
        if not rows:
            break
        out.extend(rows)
        offset += page_size
    return out, total


def _db_lower_ranks(values: set[str]) -> dict[str, int]:
    """Map each raw string to the rank of Postgres' lower(value) under the
    database's own collation. Python's str.lower() and codepoint ordering
    differ from Postgres' lower() + locale collation (e.g. en_US sorts
    "_treble" between "1985" and "A.G"), so the expected order is computed in
    Python but keyed on ranks Postgres supplies — the test then verifies the
    ORDER BY mapping (which columns, which direction, tie-breakers), not
    collation rules. Read-only: unnest() over a parameter array, no tables."""
    with psycopg.connect(settings.warehouse_dsn) as conn:
        rows = conn.execute(
            "SELECT v, dense_rank() OVER (ORDER BY lower(v)) FROM unnest(%s::text[]) AS v",
            [sorted(values)],
        ).fetchall()
    return {v: r for v, r in rows}


def test_every_genre_facet_round_trips_as_a_filter():
    stats = warehouse.get_stats()
    for g in stats["genres"]:
        _, total = warehouse.list_tracks(genre=g["genre"], limit=1)
        assert total == g["count"], g
        # Case/whitespace variants hit the same rows.
        _, total = warehouse.list_tracks(genre=f"  {g['genre'].upper()} ", limit=1)
        assert total == g["count"], g


def test_every_source_count_matches_source_filter():
    stats = warehouse.get_stats()
    assert stats["total_sources"] >= len(stats["sources"])
    for s in stats["sources"]:
        _, total = warehouse.list_tracks(source_url=s["source_url"], limit=1)
        assert total == s["track_count"], s


def test_stats_totals_are_consistent():
    stats = warehouse.get_stats()
    _, total = warehouse.list_tracks(limit=1)
    assert stats["total_tracks"] == total
    assert sum(g["count"] for g in stats["genres"]) <= total
    if total:
        assert stats["last_scraped_at"] is not None


@pytest.mark.parametrize("sort", warehouse.SORT_OPTIONS)
def test_each_sort_paginates_without_duplicates_or_gaps(sort):
    rows, total = _all_rows(sort)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), f"duplicate ids across pages for sort={sort}"
    assert len(ids) == total


@pytest.mark.parametrize("sort", warehouse.SORT_OPTIONS)
def test_each_sort_returns_rows_in_the_documented_order(sort):
    rows, _ = _all_rows(sort)
    if sort == "recent":
        # scraped_at DESC, id DESC — both keys descending, so reverse a plain sort.
        expected = sorted(rows, key=lambda r: (r["scraped_at"], r["id"]), reverse=True)
    elif sort == "popular":
        # coalesce(playback_count, 0) DESC, id DESC — a track with no known
        # count sorts as if it were 0, not last-by-nulls or excluded.
        expected = sorted(rows, key=lambda r: (r["playback_count"] or 0, r["id"]), reverse=True)
    else:
        rank = _db_lower_ranks({r["artist"] for r in rows} | {r["title"] for r in rows})
        if sort == "artist":
            key = lambda r: (rank[r["artist"]], rank[r["title"]], r["id"])  # noqa: E731
        else:  # title
            key = lambda r: (rank[r["title"]], rank[r["artist"]], r["id"])  # noqa: E731
        expected = sorted(rows, key=key)
    assert [r["id"] for r in rows] == [r["id"] for r in expected], f"sort={sort} out of order"


def test_favorited_only_with_no_user_matches_nothing():
    # favorited_only is meaningless without a real logged-in user — the
    # actual per-user filtering behavior (and cross-user isolation) needs
    # writable fixtures, so it's covered in test_favorites_integration.py
    # instead of here (this file stays strictly read-only).
    rows, total = warehouse.list_tracks(favorited_only=True, current_user_id=0, limit=200)
    assert rows == []
    assert total == 0


def test_search_metacharacters_match_literally():
    for term in ("%", "_", "\\"):
        rows, total = warehouse.list_tracks(search=term, limit=200)
        assert total == len(rows) or total > 200
        for r in rows:
            assert term in r["artist"] or term in r["title"], (term, r)
    _, everything = warehouse.list_tracks(limit=1)
    _, percent = warehouse.list_tracks(search="%", limit=1)
    if everything:
        # A lone % used to act as a wildcard and match every row.
        assert percent < everything
