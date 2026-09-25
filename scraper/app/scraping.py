import asyncio
import logging
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from .settings import settings

logger = logging.getLogger("apollo.scraping")

# Serializes all Playwright browser usage within this process. A single pod
# has a fixed CPU/memory budget (see infra/terraform-k8s/api.tf) sized for one
# Firefox+scroll session at a time — without this, two concurrent /scrape (or
# /api/discover-playlists) requests would each launch their own browser and
# could exceed it. Cross-replica concurrency is a separate, already-handled
# concern (replicas pinned to 1 — see api.tf).
_browser_semaphore = asyncio.Semaphore(1)

# Retries only cover transient navigation failures (timeout, network blip) —
# not the "requires login" case, which isn't an exception at all (SoundCloud
# returns a normal 200 with an error page, detected downstream in main.py).
_NAV_RETRY_ATTEMPTS = 3
_NAV_RETRY_BASE_DELAY_S = 1.0


async def _goto_with_retry(page, url: str) -> None:
    delay = _NAV_RETRY_BASE_DELAY_S
    for attempt in range(1, _NAV_RETRY_ATTEMPTS + 1):
        try:
            await page.goto(url, timeout=settings.scrape_timeout_ms)
            return
        except (PlaywrightTimeoutError, PlaywrightError):
            if attempt == _NAV_RETRY_ATTEMPTS:
                raise
            logger.warning(
                "Navigation to %s failed (attempt %d/%d), retrying in %.1fs",
                url, attempt, _NAV_RETRY_ATTEMPTS, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2

# SoundCloud's frontend renders track lists with a couple of different class
# combinations depending on page type (playlist vs. user stream). We try each
# in turn rather than assuming one. These are scraped from the live DOM, not
# from a public API, so they will drift when SoundCloud ships a redesign —
# if a scrape returns zero tracks, this is the first thing to re-check.
_ITEM_SELECTORS = ["li.trackList__item", "div.trackItem__content"]


def _canonical_url(url: str | None) -> str | None:
    """Strip tracking query params (e.g. `?in=<referring playlist>`) so the
    same track always maps to the same key, whether the URL came from the
    rendered DOM or from hydration state — otherwise DOM/hydration enrichment
    never matches, and the warehouse would treat the same track as a new row
    for every playlist it was scraped from."""
    if not url:
        return url
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _parse_cookie_header(raw: str) -> list[dict]:
    """Parses a raw `name=value; name2=value2` cookie header (the kind you'd
    copy from a browser's DevTools) into Playwright's cookie dict format."""
    cookies = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies.append({"name": name.strip(), "value": value.strip(), "domain": ".soundcloud.com", "path": "/"})
    return cookies


async def fetch_html(url: str) -> tuple[str, list | None]:
    """Returns (html, hydration). `hydration` is SoundCloud's live in-page
    `window.__sc_hydration` state, read via page.evaluate() *after* scrolling
    — not from the static HTML. That distinction matters: SoundCloud's SSR
    payload only fully hydrates the first handful of tracks in a playlist
    (the rest are id-only stubs); `page.content()` only ever reflects that
    initial snapshot. Scrolling triggers SoundCloud's own app to fetch full
    track details client-side and populate them into the *live* JS object —
    reading that live object after scrolling gets every track fully hydrated,
    not just the first few."""
    async with _browser_semaphore, async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        try:
            context = await browser.new_context()
            if settings.soundcloud_cookies:
                # Opt-in, user-supplied session cookies for pages that require
                # being logged in (e.g. a personal Discover Weekly). See settings.py.
                await context.add_cookies(_parse_cookie_header(settings.soundcloud_cookies))
            page = await context.new_page()
            logger.debug("Navigating to %s", url)
            await _goto_with_retry(page, url)

            last_height = await page.evaluate("document.body.scrollHeight")
            iterations = 0
            for i in range(settings.max_scroll_iterations):
                iterations = i + 1
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(settings.scroll_pause_ms)
                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            logger.debug(
                "Scrolling settled for %s after %d/%d iterations (final height %dpx)",
                url, iterations, settings.max_scroll_iterations, last_height,
            )

            html = await page.content()
            hydration = await page.evaluate("window.__sc_hydration || null")
            return html, hydration
        finally:
            await browser.close()


_PLAYLIST_HREF_RE = re.compile(r"^/[\w-]+/sets/[\w-]+/?$")


async def discover_playlists(profile_url: str) -> list[dict]:
    """Browses a SoundCloud profile's own playlist index (`/<user>/sets`) and
    returns [{name, url}] for each playlist found — this is the 'browse' half
    of the feature: see what's there before deciding what (if anything) to
    scrape. Read-only, one page fetch, same politeness as a normal scrape."""
    sets_url = profile_url.rstrip("/")
    if not sets_url.endswith("/sets"):
        sets_url = f"{sets_url}/sets"

    html, _ = await fetch_html(sets_url)
    soup = BeautifulSoup(html, "html.parser")

    playlists = []
    seen = set()
    for card in soup.find_all("div", class_="sound__body"):
        link = card.find("a", class_="sound__coverArt", href=True)
        if not link or not _PLAYLIST_HREF_RE.match(link["href"]):
            continue

        url = _canonical_url(urljoin("https://soundcloud.com/", link["href"]))
        if not url or url in seen:
            continue
        seen.add(url)

        title_el = card.find(class_="soundTitle")
        name = (title_el.get("title") if title_el else None) or url.rsplit("/", 1)[-1].replace("-", " ")
        playlists.append({"name": name, "url": url})

    logger.debug("Discovered %d playlist(s) at %s", len(playlists), sets_url)
    return playlists


def _hydration_playlist_tracks(hydration: list | None) -> list[dict]:
    if not hydration:
        return []
    playlist = next((e.get("data") for e in hydration if e.get("hydratable") == "playlist"), None)
    return playlist.get("tracks", []) if playlist else []


def _track_from_hydration(track: dict) -> dict:
    return {
        "title": track.get("title") or "",
        "artist": (track.get("user") or {}).get("username") or "Unknown Artist",
        "genre": track.get("genre") or None,
        "url": _canonical_url(track.get("permalink_url")),
        # Only ever true when SoundCloud's own data says the uploader enabled
        # downloads for this specific track — never inferred otherwise. The
        # frontend only shows a download link when this is true, and even then
        # links out to SoundCloud's own page rather than us serving the file.
        "downloadable": bool(track.get("downloadable")),
    }


def _hydration_track_info(hydration: list | None) -> dict[str, dict]:
    """Enrichment map keyed by canonical url, for topping up whatever the DOM
    parser found. Stubs (no title — SoundCloud didn't finish hydrating them,
    e.g. scrolling was cut short by max_scroll_iterations) are skipped since
    they carry no real data."""
    info = {}
    for track in _hydration_playlist_tracks(hydration):
        if not track.get("title"):
            continue
        record = _track_from_hydration(track)
        if record["url"]:
            info[record["url"]] = record
    return info


def _hydration_profile_owner(hydration: list | None) -> dict | None:
    """On a user's profile/stream page (as opposed to a playlist), SoundCloud
    doesn't render a per-track username at all when every track belongs to
    that same account — there's nothing to disambiguate. This reads who the
    profile belongs to, so tracks can be attributed to them specifically
    (verified against the track's own URL below, not assumed blindly, so a
    repost from someone else's account in the stream doesn't get mislabeled)."""
    if not hydration:
        return None
    user = next((e.get("data") for e in hydration if e.get("hydratable") == "user"), None)
    if not user or not user.get("permalink"):
        return None
    return {"permalink": user["permalink"], "username": user.get("username") or user["permalink"]}


def _parse_dom(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    items = []
    matched_selector = None
    for selector in _ITEM_SELECTORS:
        tag, _, cls = selector.partition(".")
        items = soup.find_all(tag, class_=cls)
        if items:
            matched_selector = selector
            break
    logger.debug("DOM selector %r matched %d item(s)", matched_selector, len(items))

    records = []
    for entry in items:
        title_tag = entry.find("a", class_="trackItem__trackTitle")
        artist_tag = entry.find("a", class_="trackItem__username")
        genre_tag = entry.find("a", class_="trackItem__genre")

        if not title_tag:
            logger.debug("Skipping track item with no title tag")
            continue

        href = title_tag.get("href")
        track_url = _canonical_url(urljoin("https://soundcloud.com/", href)) if href else None

        records.append(
            {
                "title": title_tag.get_text(strip=True),
                "artist": artist_tag.get_text(strip=True) if artist_tag else None,
                "genre": genre_tag.get_text(strip=True) if genre_tag else None,
                "url": track_url,
                "downloadable": False,  # DOM has no signal for this — only hydration enrichment sets it true
            }
        )
    return records


def parse_html(html: str, hydration: list | None, source_url: str) -> list[dict]:
    """Track list, primarily from SoundCloud's own (post-scroll, fully
    hydrated) in-page state — CSS/DOM scraping is only the fallback, used
    when hydration is missing entirely (a page type without it) or to fill
    in artist/genre for the odd track hydration didn't finish loading."""
    if not html:
        return []

    records = _parse_dom(html)
    hydration_info = _hydration_track_info(hydration)
    profile_owner = _hydration_profile_owner(hydration)
    logger.debug(
        "parse_html(%s): %d DOM record(s), %d hydration-enrichable, profile_owner=%s",
        source_url, len(records), len(hydration_info), profile_owner["permalink"] if profile_owner else None,
    )

    if not records:
        logger.warning("DOM parse found 0 tracks for %s — falling back to hydration data only", source_url)
        records = [_track_from_hydration(t) for t in _hydration_playlist_tracks(hydration)]

    for record in records:
        enrichment = hydration_info.get(record["url"]) if record["url"] else None
        if enrichment:
            record["artist"] = enrichment["artist"]
            record["genre"] = enrichment["genre"]
            record["downloadable"] = enrichment["downloadable"]
        elif not record.get("artist"):
            # No per-track username in the DOM and no hydration entry for this
            # track (e.g. a profile/stream page — see _hydration_profile_owner).
            # Only attribute it to the profile owner when the track's own URL
            # confirms they're actually the uploader, so a repost from someone
            # else in the stream isn't mislabeled.
            owner_permalink = urlsplit(record["url"]).path.strip("/").split("/")[0] if record["url"] else None
            if profile_owner and owner_permalink == profile_owner["permalink"]:
                record["artist"] = profile_owner["username"]
            else:
                record["artist"] = "Unknown Artist"

    if not records:
        logger.warning("Parsed 0 tracks from %s — selectors may be stale", source_url)

    return records
