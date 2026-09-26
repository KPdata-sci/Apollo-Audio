import logging
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from .settings import settings

logger = logging.getLogger("apollo.warehouse")

_UPSERT_SQL = """
INSERT INTO tracks (artist, title, genre, url, downloadable, playback_count, likes_count, artwork_url, source_url, lake_object_key, scraped_at)
VALUES (%(artist)s, %(title)s, %(genre)s, %(url)s, %(downloadable)s, %(playback_count)s, %(likes_count)s, %(artwork_url)s, %(source_url)s, %(lake_object_key)s, %(scraped_at)s)
ON CONFLICT (url) DO UPDATE SET
    artist = EXCLUDED.artist,
    title = EXCLUDED.title,
    genre = EXCLUDED.genre,
    downloadable = EXCLUDED.downloadable,
    -- Popularity counters and artwork are just SoundCloud's own live data,
    -- refreshed on every rescrape like any other column here — unlike a
    -- favorite (see the `favorites` table), there's no "don't overwrite" concern.
    playback_count = EXCLUDED.playback_count,
    likes_count = EXCLUDED.likes_count,
    artwork_url = EXCLUDED.artwork_url,
    source_url = EXCLUDED.source_url,
    lake_object_key = EXCLUDED.lake_object_key,
    scraped_at = EXCLUDED.scraped_at
"""

_INSERT_NO_URL_SQL = """
INSERT INTO tracks (artist, title, genre, url, downloadable, playback_count, likes_count, artwork_url, source_url, lake_object_key, scraped_at)
VALUES (%(artist)s, %(title)s, %(genre)s, %(url)s, %(downloadable)s, %(playback_count)s, %(likes_count)s, %(artwork_url)s, %(source_url)s, %(lake_object_key)s, %(scraped_at)s)
"""


# Normalized genre key shared by the `genre` filter and the /api/stats genre
# facet, so every facet value round-trips as a filter. btrim with an explicit
# whitespace set (not bare trim(), which only strips spaces) so a stray
# tab/newline from scraped data can't split one genre into two keys.
_GENRE_KEY = "lower(btrim(genre, E' \\t\\r\\n'))"
_GENRE_PARAM_KEY = "lower(btrim(%(genre)s, E' \\t\\r\\n'))"


def escape_like(term: str) -> str:
    """Escape LIKE metacharacters so `term` matches literally. Pairs with the
    explicit `ESCAPE '\\'` in _WHERE; backslash must be escaped first."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# LEFT JOIN so a track with no favorites-row still comes back (favorited =
# false) instead of being dropped from every listing. Bare column names below
# (artist, title, id, playback_count, ...) are unambiguous against this join —
# `favorites` only has track_id/created_at, never a name that collides.
_FROM = "FROM tracks LEFT JOIN favorites f ON f.track_id = tracks.id"

# `search` is a literal (case-insensitive) substring match: the user's term is
# run through escape_like() before being wrapped in %...%.
_WHERE = f"""
WHERE (%(search)s = ''
       OR artist ILIKE %(pattern)s ESCAPE '\\'
       OR title ILIKE %(pattern)s ESCAPE '\\')
  AND (%(genre)s = '' OR {_GENRE_KEY} = {_GENRE_PARAM_KEY})
  AND (%(source_url)s = '' OR source_url = %(source_url)s)
  AND (%(favorited_only)s = false OR f.track_id IS NOT NULL)
"""

# Whitelisted ORDER BY clauses. User input only ever selects a key here — it is
# never interpolated into SQL. Every clause ends in `id` so pagination is
# stable when the leading columns tie. "recent" is the original ordering.
# "popular" treats a track with no known playback_count (DOM-only parse, or
# hydration just never carried it) as 0 rather than excluding it — it should
# sort last among "popular" results, not vanish from them.
_ORDER_BY = {
    "recent": "scraped_at DESC, id DESC",
    "artist": "lower(artist) ASC, lower(title) ASC, id ASC",
    "title": "lower(title) ASC, lower(artist) ASC, id ASC",
    "popular": "coalesce(playback_count, 0) DESC, id DESC",
}
SORT_OPTIONS = tuple(_ORDER_BY)

# Pre-built once at import from constants only (no user input involved).
# count(*) OVER() rides along with the page query so the common case (rows
# come back) is one round trip instead of two identical WHERE evaluations;
# an empty page (offset past the end) has no row to carry a total on, so
# list_tracks() falls back to _COUNT_SQL only in that case.
_LIST_SQL_BY_SORT = {
    key: f"""
SELECT tracks.id, artist, title, genre, url, downloadable, playback_count, likes_count, artwork_url,
       (f.track_id IS NOT NULL) AS favorited, source_url, scraped_at,
       count(*) OVER() AS total
{_FROM}
{_WHERE}
ORDER BY {order_by}
LIMIT %(limit)s OFFSET %(offset)s
"""
    for key, order_by in _ORDER_BY.items()
}

_COUNT_SQL = f"""
SELECT count(*) AS total
{_FROM}
{_WHERE}
"""


def list_tracks(
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    genre: str = "",
    source_url: str = "",
    sort: str = "recent",
    favorited_only: bool = False,
) -> tuple[list[dict], int]:
    try:
        list_sql = _LIST_SQL_BY_SORT[sort]
    except KeyError:
        raise ValueError(f"Unsupported sort {sort!r}; expected one of {SORT_OPTIONS}") from None

    params = {
        "search": search,
        "pattern": f"%{escape_like(search)}%",
        "genre": genre,
        "source_url": source_url,
        "favorited_only": favorited_only,
        "limit": limit,
        "offset": offset,
    }

    with psycopg.connect(settings.warehouse_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(list_sql, params)
            rows = cur.fetchall()
            if rows:
                total = rows[0].pop("total")
                for row in rows[1:]:
                    del row["total"]
            else:
                cur.execute(_COUNT_SQL, params)
                total = cur.fetchone()["total"]

    logger.debug(
        "list_tracks(search=%r, genre=%r, source_url=%r, sort=%s, favorited_only=%s, limit=%d, offset=%d) "
        "-> %d row(s) of %d total",
        search, genre, source_url, sort, favorited_only, limit, offset, len(rows), total,
    )
    return rows, total


# Genre facet. Grouped on the same normalized key as the `genre` filter. The
# display value is the most common trimmed spelling within the group (ties ->
# first in byte order, which prefers capitalized forms, e.g. "Piano" over
# "piano"). Hashtag soup ("artist#cover#piano") is uploader tag spam rather
# than a genre, so it's left out of the facet list — those rows are still
# counted in total_tracks and still reachable via the `genre` filter.
_GENRE_FACET_SQL = f"""
WITH spellings AS (
    SELECT {_GENRE_KEY} AS key,
           btrim(genre, E' \\t\\r\\n') AS spelling,
           count(*) AS n
    FROM tracks
    WHERE genre IS NOT NULL
      AND btrim(genre, E' \\t\\r\\n') <> ''
      AND strpos(genre, '#') = 0
    GROUP BY 1, 2
),
display AS (
    SELECT DISTINCT ON (key) key, spelling
    FROM spellings
    ORDER BY key, n DESC, spelling COLLATE "C"
),
totals AS (
    SELECT key, sum(n)::int AS count FROM spellings GROUP BY key
)
SELECT d.spelling AS genre, t.count
FROM display d JOIN totals t USING (key)
ORDER BY t.count DESC, d.key ASC
LIMIT %(limit)s
"""

_SOURCES_SQL = """
SELECT source_url, count(*)::int AS track_count, max(scraped_at) AS last_scraped_at
FROM tracks
GROUP BY source_url
ORDER BY last_scraped_at DESC, source_url ASC
LIMIT %(limit)s
"""

_TOTALS_SQL = """
SELECT count(*)::int AS total_tracks,
       count(DISTINCT source_url)::int AS total_sources,
       (SELECT count(*) FROM favorites)::int AS total_favorites,
       max(scraped_at) AS last_scraped_at
FROM tracks
"""


def get_stats(genre_limit: int = 40, source_limit: int = 100) -> dict:
    """Warehouse overview for GET /api/stats — see main.py for the shape."""
    with psycopg.connect(settings.warehouse_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(_TOTALS_SQL)
            totals = cur.fetchone()
            cur.execute(_GENRE_FACET_SQL, {"limit": genre_limit})
            genres = cur.fetchall()
            cur.execute(_SOURCES_SQL, {"limit": source_limit})
            sources = cur.fetchall()

    logger.debug(
        "get_stats -> %d track(s), %d source(s), %d favorite(s), %d genre facet(s)",
        totals["total_tracks"], totals["total_sources"], totals["total_favorites"], len(genres),
    )
    return {**totals, "genres": genres, "sources": sources}


def load_tracks(
    tracks: list[dict],
    source_url: str,
    lake_object_key: str,
    scraped_at: datetime,
) -> int:
    """Load parsed tracks from a lake object into the warehouse. Upserts on
    `url` (a track's stable identity) so re-scrapes refresh a row instead of
    duplicating it; tracks with no url (parser couldn't find a link) are
    inserted as-is since there's nothing stable to dedupe them on."""
    if not tracks:
        return 0

    rows = [
        {
            "artist": t["artist"],
            "title": t["title"],
            "genre": t.get("genre"),
            "url": t.get("url"),
            "downloadable": bool(t.get("downloadable")),
            "playback_count": t.get("playback_count"),
            "likes_count": t.get("likes_count"),
            "artwork_url": t.get("artwork_url"),
            "source_url": source_url,
            "lake_object_key": lake_object_key,
            "scraped_at": scraped_at,
        }
        for t in tracks
    ]

    with_url = [r for r in rows if r["url"]]
    without_url = [r for r in rows if not r["url"]]
    no_url_count = len(without_url)

    # executemany batches these over the wire instead of one round trip per
    # track — a 200-track playlist was 200 sequential execute() calls before.
    with psycopg.connect(settings.warehouse_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if with_url:
                cur.executemany(_UPSERT_SQL, with_url)
            if without_url:
                cur.executemany(_INSERT_NO_URL_SQL, without_url)
        conn.commit()

    logger.debug(
        "load_tracks: upserted %d row(s) for %s (%d had no url, inserted as-is)",
        len(rows), source_url, no_url_count,
    )
    return len(rows)


_ADD_FAVORITE_SQL = "INSERT INTO favorites (track_id) VALUES (%(track_id)s) ON CONFLICT (track_id) DO NOTHING"
_REMOVE_FAVORITE_SQL = "DELETE FROM favorites WHERE track_id = %(track_id)s"
_TRACK_EXISTS_SQL = "SELECT 1 FROM tracks WHERE id = %(track_id)s"


def add_favorite(track_id: int) -> bool:
    """Marks a track as favorited. Idempotent — favoriting an already-favorited
    track is a no-op, not an error (`ON CONFLICT DO NOTHING`), since the caller
    only cares that it ends up favorited, not whether this call was the one
    that did it. Returns False when no track with this id exists, so the
    caller can turn that into a 404 rather than silently favoriting nothing."""
    with psycopg.connect(settings.warehouse_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(_TRACK_EXISTS_SQL, {"track_id": track_id})
            if cur.fetchone() is None:
                return False
            cur.execute(_ADD_FAVORITE_SQL, {"track_id": track_id})
        conn.commit()
    logger.debug("add_favorite(%d)", track_id)
    return True


def remove_favorite(track_id: int) -> bool:
    """Un-favorites a track. Same idempotent shape as add_favorite: removing a
    favorite that was never set is a no-op, not an error. Returns False only
    when no track with this id exists at all."""
    with psycopg.connect(settings.warehouse_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(_TRACK_EXISTS_SQL, {"track_id": track_id})
            if cur.fetchone() is None:
                return False
            cur.execute(_REMOVE_FAVORITE_SQL, {"track_id": track_id})
        conn.commit()
    logger.debug("remove_favorite(%d)", track_id)
    return True
