"""Browser-driven smoke test against the real, running frontend — one level
above the API/warehouse integration tests: confirms the actual page a person
sees still works, not just that the endpoints it calls do (see
docs/NEXT_STEPS.md's original ask for "a small Playwright smoke test: load,
filter, open the player").

Skipped unless APOLLO_FRONTEND_URL is set. Only CI's compose-smoke job (which
boots the real docker-compose stack) sets it — the plain unit-test run
doesn't, so this never runs there and never needs Chromium installed for it.
pytest-playwright (not in scraper/requirements.txt — this is a test-only
dependency, never shipped in the production image) provides the `page`
fixture used below.
"""
import os

import pytest

pytest.importorskip("playwright")

FRONTEND_URL = os.environ.get("APOLLO_FRONTEND_URL", "")

pytestmark = pytest.mark.skipif(not FRONTEND_URL, reason="APOLLO_FRONTEND_URL not set")


def test_library_loads_and_shows_tracks(page):
    page.goto(f"{FRONTEND_URL}/#library")
    page.wait_for_selector(".track", timeout=15000)
    assert page.locator(".track").count() > 0


def test_search_filters_the_track_list(page):
    page.goto(f"{FRONTEND_URL}/#library")
    page.wait_for_selector(".track", timeout=15000)
    before = page.locator(".track").count()

    page.fill("#search", "zzz-no-such-track-should-ever-match-zzz")
    page.wait_for_timeout(1000)  # the search box is debounced client-side

    after_filtered = page.locator(".state").count() > 0 or page.locator(".track").count() < before
    assert after_filtered


def test_play_opens_the_docked_player(page):
    page.goto(f"{FRONTEND_URL}/#library")
    page.wait_for_selector("[data-play]", timeout=15000)
    page.locator("[data-play]").first.click()

    page.wait_for_selector("#player-dock:not([hidden])", timeout=5000)
    assert page.locator("#dock-frame iframe").count() > 0
