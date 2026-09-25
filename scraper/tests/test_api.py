from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import warehouse
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@patch("app.pipeline.warehouse.load_tracks", return_value=1)
@patch("app.pipeline.lake.put_raw_scrape", return_value="raw/soundcloud/fake.json")
@patch("app.pipeline.fetch_html", new_callable=AsyncMock)
def test_scrape_endpoint_lands_in_lake_then_warehouse(mock_fetch, mock_put_raw, mock_load, monkeypatch):
    mock_fetch.return_value = (
        """
        <li class="trackList__item">
            <a class="trackItem__trackTitle" href="/a/b">Song</a>
            <a class="trackItem__username">Artist</a>
        </li>
        """,
        None,  # no hydration state for this page
    )

    resp = client.post("/scrape", json={"url": "https://soundcloud.com/a/sets/b"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["track_count"] == 1
    assert body["lake_object_key"] == "raw/soundcloud/fake.json"

    mock_put_raw.assert_called_once()
    mock_load.assert_called_once()


@patch("app.main.warehouse.list_tracks")
def test_list_tracks_endpoint(mock_list_tracks):
    mock_list_tracks.return_value = (
        [
            {
                "id": 1,
                "artist": "Artist",
                "title": "Song",
                "genre": None,
                "url": "https://soundcloud.com/artist/song",
                "source_url": "https://soundcloud.com/artist/sets/x",
                "scraped_at": "2026-01-01T00:00:00Z",
            }
        ],
        1,
    )

    resp = client.get("/api/tracks?search=song&limit=10&offset=0")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Song"
    mock_list_tracks.assert_called_once_with(
        search="song", limit=10, offset=0, genre="", source_url="", sort="recent"
    )


@patch("app.main.warehouse.list_tracks", return_value=([], 0))
def test_list_tracks_passes_filters_and_sort(mock_list_tracks):
    resp = client.get(
        "/api/tracks",
        params={
            "search": "  song ",
            "genre": "Drum & Bass",
            "source_url": " https://soundcloud.com/a/sets/b ",
            "sort": "artist",
            "limit": 500,
            "offset": -3,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "limit": 200, "offset": 0}
    mock_list_tracks.assert_called_once_with(
        search="song",
        limit=200,
        offset=0,
        genre="Drum & Bass",
        source_url="https://soundcloud.com/a/sets/b",
        sort="artist",
    )


@patch("app.main.warehouse.list_tracks", return_value=([], 0))
def test_list_tracks_blank_filters_mean_no_filter(mock_list_tracks):
    resp = client.get("/api/tracks", params={"genre": "   ", "source_url": "", "sort": "title"})

    assert resp.status_code == 200
    kwargs = mock_list_tracks.call_args.kwargs
    assert kwargs["genre"] == ""
    assert kwargs["source_url"] == ""
    assert kwargs["sort"] == "title"


@patch("app.main.warehouse.list_tracks")
def test_list_tracks_rejects_invalid_sort(mock_list_tracks):
    for bad in ("scraped_at DESC; DROP TABLE tracks", "RECENT", "genre"):
        resp = client.get("/api/tracks", params={"sort": bad})
        assert resp.status_code == 422, bad
    mock_list_tracks.assert_not_called()


def test_warehouse_list_tracks_rejects_unknown_sort_directly():
    # Defense in depth: the warehouse layer only accepts whitelisted keys even
    # if a caller other than the endpoint forgets to validate.
    with pytest.raises(ValueError):
        warehouse.list_tracks(sort="id; DROP TABLE tracks")


@patch("app.main.warehouse.list_tracks", return_value=([], 0))
def test_list_tracks_rejects_nul_bytes(mock_list_tracks):
    # Postgres rejects NUL in text; this used to surface as an unhandled 500.
    for query in ("genre=%00", "source_url=a%00b", "search=x%00", "search=ok&genre=Pop%00"):
        resp = client.get(f"/api/tracks?{query}")
        assert resp.status_code == 422, query
        assert "NUL" in resp.json()["detail"]
    mock_list_tracks.assert_not_called()


def test_escape_like_makes_metacharacters_literal():
    assert warehouse.escape_like("plain text") == "plain text"
    assert warehouse.escape_like("100%") == "100\\%"
    assert warehouse.escape_like("a_b") == "a\\_b"
    # Backslash is escaped first, so an existing "\%" can't un-escape itself.
    assert warehouse.escape_like("\\%") == "\\\\\\%"
    assert warehouse.escape_like("%_\\") == "\\%\\_\\\\"


@patch("app.warehouse.psycopg.connect")
def test_list_tracks_sql_uses_escaped_pattern_and_escape_clause(mock_connect):
    cur = mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    cur.fetchone.return_value = {"total": 0}

    warehouse.list_tracks(search="50%_off")

    sql, params = cur.execute.call_args_list[0].args
    assert params["pattern"] == "%50\\%\\_off%"
    assert sql.count("ESCAPE '\\'") == 2
    count_sql, _ = cur.execute.call_args_list[1].args
    assert count_sql.count("ESCAPE '\\'") == 2


@patch("app.main.warehouse.get_stats")
def test_stats_endpoint(mock_get_stats):
    mock_get_stats.return_value = {
        "total_tracks": 5,
        "total_sources": 2,
        "last_scraped_at": "2026-09-25T17:22:00Z",
        "genres": [{"genre": "Drum & Bass", "count": 3}, {"genre": "Piano", "count": 2}],
        "sources": [
            {
                "source_url": "https://soundcloud.com/a/sets/b",
                "track_count": 3,
                "last_scraped_at": "2026-09-25T17:22:00Z",
            },
            {
                "source_url": "https://soundcloud.com/c",
                "track_count": 2,
                "last_scraped_at": "2026-09-24T10:00:00Z",
            },
        ],
    }

    resp = client.get("/api/stats")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_tracks"] == 5
    assert body["total_sources"] == 2
    assert body["last_scraped_at"].startswith("2026-09-25T17:22:00")
    assert body["genres"][0] == {"genre": "Drum & Bass", "count": 3}
    assert [s["source_url"] for s in body["sources"]] == [
        "https://soundcloud.com/a/sets/b",
        "https://soundcloud.com/c",
    ]
    assert set(body["sources"][0]) == {"source_url", "track_count", "last_scraped_at"}
    mock_get_stats.assert_called_once_with(genre_limit=40, source_limit=100)


@patch("app.main.warehouse.get_stats")
def test_stats_endpoint_empty_warehouse(mock_get_stats):
    mock_get_stats.return_value = {
        "total_tracks": 0,
        "total_sources": 0,
        "last_scraped_at": None,
        "genres": [],
        "sources": [],
    }

    resp = client.get("/api/stats")

    assert resp.status_code == 200
    assert resp.json() == {
        "total_tracks": 0,
        "total_sources": 0,
        "last_scraped_at": None,
        "genres": [],
        "sources": [],
    }


@patch("app.main.warehouse.get_stats")
def test_get_api_responses_revalidate_with_etag(mock_get_stats):
    mock_get_stats.return_value = {
        "total_tracks": 0, "total_sources": 0, "last_scraped_at": None, "genres": [], "sources": [],
    }

    first = client.get("/api/stats")
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"

    repeat = client.get("/api/stats", headers={"If-None-Match": etag})
    assert repeat.status_code == 304
    assert repeat.content == b""

    mock_get_stats.return_value = {**mock_get_stats.return_value, "total_tracks": 1}
    changed = client.get("/api/stats", headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag


def test_catalog_is_cacheable_and_gzipped():
    resp = client.get("/api/playlists", headers={"Accept-Encoding": "gzip"})

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=3600"
    assert resp.headers["content-encoding"] == "gzip"


def test_write_endpoints_are_not_etagged():
    resp = client.post("/scrape", json={"url": "http://example.com"})

    assert resp.status_code == 422
    assert "etag" not in resp.headers


def test_playlist_catalog_endpoint_shape():
    # Contents are curated in scraper/app/playlists.py and may change freely —
    # only the shape is part of the API contract.
    resp = client.get("/api/playlists")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    for genre, entries in body.items():
        assert isinstance(genre, str)
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, dict)
            assert isinstance(entry["name"], str)
            assert isinstance(entry["url"], str)


@patch("app.pipeline.warehouse.load_tracks")
@patch("app.pipeline.lake.put_raw_scrape")
@patch("app.pipeline.fetch_html", new_callable=AsyncMock)
def test_scrape_returns_422_when_page_requires_login(mock_fetch, mock_put_raw, mock_load):
    mock_fetch.return_value = (
        "<html><body>You may have to log in to view this playlist, or it may have been deleted.</body></html>",
        None,
    )

    resp = client.post("/scrape", json={"url": "https://soundcloud.com/discover/sets/weekly::someone"})

    assert resp.status_code == 422
    assert "APOLLO_SOUNDCLOUD_COOKIES" in resp.json()["detail"]
    mock_put_raw.assert_not_called()
    mock_load.assert_not_called()


def test_scrape_rejects_non_soundcloud_url():
    resp = client.post("/scrape", json={"url": "http://169.254.169.254/latest/meta-data/"})

    assert resp.status_code == 422
    assert "soundcloud.com" in resp.json()["detail"]


def test_discover_playlists_rejects_non_soundcloud_url():
    resp = client.post("/api/discover-playlists", json={"profile_url": "http://example.com"})

    assert resp.status_code == 422
    assert "soundcloud.com" in resp.json()["detail"]
