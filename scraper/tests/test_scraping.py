import asyncio
from unittest.mock import AsyncMock, patch

from app.scraping import discover_playlists, parse_html

PROFILE_SETS_HTML = """
<html><body>
<div class="sound__body">
  <div class="sound__artwork">
    <a class="sound__coverArt" href="/someartist/sets/first-playlist"></a>
  </div>
  <div class="sound__content">
    <div class="soundTitle" title="First Playlist"></div>
  </div>
</div>
<div class="sound__body">
  <div class="sound__artwork">
    <a class="sound__coverArt" href="/someartist/sets/second-playlist"></a>
  </div>
  <div class="sound__content">
    <div class="soundTitle" title="Second Playlist"></div>
  </div>
</div>
<div class="sound__body">
  <!-- not a playlist card — no matching href, must be skipped -->
  <a class="sound__coverArt" href="/someartist/a-track"></a>
</div>
</body></html>
"""

PLAYLIST_HTML = """
<html><body>
<ul>
  <li class="trackList__item">
    <a class="trackItem__trackTitle" href="/artist-one/track-one">Track One</a>
    <a class="trackItem__username">Artist One</a>
    <a class="trackItem__genre">Drum & Bass</a>
  </li>
  <li class="trackList__item">
    <a class="trackItem__trackTitle" href="/artist-two/track-two">Track Two</a>
  </li>
</ul>
</body></html>
"""

STREAM_HTML = """
<html><body>
<div class="trackItem__content sc-truncate">
  <a class="trackItem__trackTitle" href="/artist-three/track-three">Track Three</a>
  <a class="trackItem__username">Artist Three</a>
</div>
</body></html>
"""


def _hydration(playlist_data):
    return [{"hydratable": "playlist", "data": playlist_data}]


def test_parse_playlist_markup_no_hydration():
    tracks = parse_html(PLAYLIST_HTML, hydration=None, source_url="https://soundcloud.com/x/sets/y")

    assert len(tracks) == 2
    assert tracks[0] == {
        "title": "Track One",
        "artist": "Artist One",
        "genre": "Drum & Bass",
        "url": "https://soundcloud.com/artist-one/track-one",
        "downloadable": False,
        "playback_count": None,
        "likes_count": None,
    }
    # Missing username/genre tags fall back cleanly instead of raising.
    assert tracks[1]["artist"] == "Unknown Artist"
    assert tracks[1]["genre"] is None
    assert tracks[1]["downloadable"] is False
    assert tracks[1]["playback_count"] is None
    assert tracks[1]["likes_count"] is None


def test_parse_stream_markup_fallback_selector():
    tracks = parse_html(STREAM_HTML, hydration=None, source_url="https://soundcloud.com/x")

    assert len(tracks) == 1
    assert tracks[0]["title"] == "Track Three"


def test_parse_empty_html_returns_empty_list():
    assert parse_html("", hydration=None, source_url="https://soundcloud.com/x") == []


def test_hydration_enriches_dom_parsed_tracks():
    # DOM has no username/genre for "Track Two" — live hydration state (as read
    # via page.evaluate() post-scroll, not the static HTML) fills it in.
    hydration = _hydration(
        {
            "tracks": [
                {
                    "title": "Track Two",
                    "genre": "House",
                    "permalink_url": "https://soundcloud.com/artist-two/track-two",
                    "user": {"username": "Real Artist Two"},
                    "downloadable": True,
                    "playback_count": 4200,
                    "likes_count": 137,
                }
            ]
        }
    )

    tracks = parse_html(PLAYLIST_HTML, hydration=hydration, source_url="https://soundcloud.com/x/sets/y")

    assert tracks[0]["artist"] == "Artist One"  # untouched — no hydration entry for this url
    assert tracks[0]["playback_count"] is None
    assert tracks[1] == {
        "title": "Track Two",
        "artist": "Real Artist Two",
        "genre": "House",
        "url": "https://soundcloud.com/artist-two/track-two",
        "downloadable": True,
        "playback_count": 4200,
        "likes_count": 137,
    }


def test_hydration_stub_without_title_is_not_used_for_enrichment():
    # A track hydration hasn't finished loading (e.g. scroll cut short) has no
    # title — must not overwrite a DOM-parsed record with blank data.
    hydration = _hydration({"tracks": [{"permalink_url": "https://soundcloud.com/artist-one/track-one"}]})

    tracks = parse_html(PLAYLIST_HTML, hydration=hydration, source_url="https://soundcloud.com/x/sets/y")

    assert tracks[0]["artist"] == "Artist One"


def test_falls_back_to_hydration_only_when_dom_has_no_tracks():
    hydration = _hydration(
        {
            "tracks": [
                {
                    "title": "Hydrated Track",
                    "genre": "Drum & Bass",
                    "permalink_url": "https://soundcloud.com/artist/hydrated-track",
                    "user": {"username": "Real Artist"},
                }
            ]
        }
    )

    tracks = parse_html("<html><body>no track markup here</body></html>", hydration=hydration, source_url="https://soundcloud.com/x/sets/y")

    assert tracks == [
        {
            "title": "Hydrated Track",
            "artist": "Real Artist",
            "genre": "Drum & Bass",
            "url": "https://soundcloud.com/artist/hydrated-track",
            "downloadable": False,
            "playback_count": None,
            "likes_count": None,
        }
    ]


def test_profile_page_attributes_tracks_to_the_verified_owner():
    # A user profile/stream page has no "playlist" hydration entry at all —
    # just a "user" one describing whose profile it is. Tracks whose own URL
    # confirms they belong to that account get attributed to them; a repost
    # from someone else's URL does not.
    hydration = [
        {"hydratable": "user", "data": {"permalink": "someuser", "username": "Some Artist"}},
    ]
    html = """
    <li class="trackList__item">
        <a class="trackItem__trackTitle" href="/someuser/some-track">Some Track</a>
    </li>
    <li class="trackList__item">
        <a class="trackItem__trackTitle" href="/someone-else/reposted-track">Reposted Track</a>
    </li>
    """

    tracks = parse_html(html, hydration=hydration, source_url="https://soundcloud.com/someuser")

    assert tracks[0]["artist"] == "Some Artist"
    assert tracks[1]["artist"] == "Unknown Artist"


@patch("app.scraping.fetch_html", new_callable=AsyncMock)
def test_discover_playlists_extracts_cards_and_skips_non_playlist_links(mock_fetch):
    mock_fetch.return_value = (PROFILE_SETS_HTML, None)

    playlists = asyncio.run(discover_playlists("https://soundcloud.com/someartist"))

    assert playlists == [
        {"name": "First Playlist", "url": "https://soundcloud.com/someartist/sets/first-playlist"},
        {"name": "Second Playlist", "url": "https://soundcloud.com/someartist/sets/second-playlist"},
    ]
    # Appends /sets to a bare profile URL rather than requiring the caller to know that.
    mock_fetch.assert_called_once_with("https://soundcloud.com/someartist/sets")
