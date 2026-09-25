"""Integrity checks for the curated playlist catalog (app/playlists.py).

These are static checks only — they never touch SoundCloud. Whether each
entry actually scrapes is verified out-of-band with the real scraper (see the
comment block at the top of playlists.py)."""
import re
from urllib.parse import urlsplit

import pytest

from app.models import PlaylistEntry
from app.pipeline import is_allowed_host
from app.playlists import CATALOG, list_playlists

ALL_ENTRIES = [(genre, entry) for genre, entries in CATALOG.items() for entry in entries]

# /<user>/sets/<slug> (a playlist) or /<user> (a whole profile).
_SET_PATH_RE = re.compile(r"^/[\w-]+/sets/[\w-]+$")
_PROFILE_PATH_RE = re.compile(r"^/[\w-]+$")


def _id(param):
    genre, entry = param
    return f"{genre}:{entry.name}"


def test_catalog_is_populated():
    assert CATALOG, "catalog should not be empty"
    assert len(CATALOG) >= 12
    for genre, entries in CATALOG.items():
        assert len(entries) >= 3, f"{genre!r} has fewer than 3 playlists"


def test_list_playlists_returns_catalog():
    assert list_playlists() is CATALOG


def test_genre_names_are_clean():
    for genre in CATALOG:
        assert isinstance(genre, str)
        assert genre.strip() == genre and genre, f"bad genre name {genre!r}"
    lowered = [g.lower() for g in CATALOG]
    assert len(lowered) == len(set(lowered)), "duplicate genre names (case-insensitive)"


@pytest.mark.parametrize("item", ALL_ENTRIES, ids=_id)
def test_entry_is_valid_playlist_entry(item):
    _, entry = item
    assert isinstance(entry, PlaylistEntry)
    # Round-trips through the API model unchanged.
    assert PlaylistEntry.model_validate(entry.model_dump()) == entry
    assert entry.name and entry.name.strip() == entry.name
    if entry.note is not None:
        assert entry.note.strip(), "note should be None rather than blank"


@pytest.mark.parametrize("item", ALL_ENTRIES, ids=_id)
def test_entry_url_is_https_soundcloud(item):
    _, entry = item
    parts = urlsplit(entry.url)
    assert parts.scheme == "https"
    assert parts.hostname == "soundcloud.com", "use the canonical soundcloud.com host, not m./www."
    assert is_allowed_host(entry.url), "the /scrape endpoint would reject this url"
    assert not parts.query and not parts.fragment, "no tracking params (e.g. ?in=, ?si=)"
    assert _SET_PATH_RE.match(parts.path) or _PROFILE_PATH_RE.match(parts.path), parts.path


@pytest.mark.parametrize("item", ALL_ENTRIES, ids=_id)
def test_profile_urls_are_labelled(item):
    """Anything that isn't a /sets/ playlist must say so in its note, so the UI
    doesn't present a whole profile as if it were a playlist."""
    _, entry = item
    if "/sets/" not in entry.url:
        assert entry.note and "profile" in entry.note.lower()


def test_no_duplicate_urls():
    urls = [e.url.rstrip("/").lower() for _, e in ALL_ENTRIES]
    dupes = {u for u in urls if urls.count(u) > 1}
    assert not dupes, f"duplicate urls: {sorted(dupes)}"


def test_no_duplicate_names_within_a_genre():
    for genre, entries in CATALOG.items():
        names = [e.name.lower() for e in entries]
        assert len(names) == len(set(names)), f"duplicate playlist names in {genre!r}"
