import logging
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from .settings import settings

logger = logging.getLogger("apollo.warehouse")

_UPSERT_SQL = """
INSERT INTO tracks (artist, title, genre, url, downloadable, source_url, lake_object_key, scraped_at)
VALUES (%(artist)s, %(title)s, %(genre)s, %(url)s, %(downloadable)s, %(source_url)s, %(lake_object_key)s, %(scraped_at)s)
ON CONFLICT (url) DO UPDATE SET
    artist = EXCLUDED.artist,
    title = EXCLUDED.title,
    genre = EXCLUDED.genre,
    downloadable = EXCLUDED.downloadable,
    source_url = EXCLUDED.source_url,
    lake_object_key = EXCLUDED.lake_object_key,
    scraped_at = EXCLUDED.scraped_at
"""

_INSERT_NO_URL_SQL = """
INSERT INTO tracks (artist, title, genre, url, downloadable, source_url, lake_object_key, scraped_at)
VALUES (%(artist)s, %(title)s, %(genre)s, %(url)s, %(downloadable)s, %(source_url)s, %(lake_object_key)s, %(scraped_at)s)
"""


_LIST_SQL = """
SELECT id, artist, title, genre, url, downloadable, source_url, scraped_at
FROM tracks
WHERE (%(search)s = '' OR artist ILIKE %(pattern)s OR title ILIKE %(pattern)s)
ORDER BY scraped_at DESC, id DESC
LIMIT %(limit)s OFFSET %(offset)s
"""

_COUNT_SQL = """
SELECT count(*) AS total FROM tracks
WHERE (%(search)s = '' OR artist ILIKE %(pattern)s OR title ILIKE %(pattern)s)
"""


def list_tracks(search: str = "", limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    params = {"search": search, "pattern": f"%{search}%", "limit": limit, "offset": offset}

    with psycopg.connect(settings.warehouse_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(_LIST_SQL, params)
            rows = cur.fetchall()
            cur.execute(_COUNT_SQL, params)
            total = cur.fetchone()["total"]

    logger.debug(
        "list_tracks(search=%r, limit=%d, offset=%d) -> %d row(s) of %d total",
        search, limit, offset, len(rows), total,
    )
    return rows, total


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
            "source_url": source_url,
            "lake_object_key": lake_object_key,
            "scraped_at": scraped_at,
        }
        for t in tracks
    ]

    no_url_count = sum(1 for r in rows if not r["url"])

    with psycopg.connect(settings.warehouse_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(_UPSERT_SQL if row["url"] else _INSERT_NO_URL_SQL, row)
        conn.commit()

    logger.debug(
        "load_tracks: upserted %d row(s) for %s (%d had no url, inserted as-is)",
        len(rows), source_url, no_url_count,
    )
    return len(rows)
