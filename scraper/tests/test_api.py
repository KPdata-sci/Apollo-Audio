from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

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
    mock_list_tracks.assert_called_once_with(search="song", limit=10, offset=0)


def test_playlist_catalog_endpoint_is_empty_by_default():
    # Ships generic — no third-party or personal accounts baked in. Anyone
    # using this adds their own entries to scraper/app/playlists.py.
    resp = client.get("/api/playlists")

    assert resp.status_code == 200
    assert resp.json() == {}


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
