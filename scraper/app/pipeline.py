import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import lake, warehouse
from .scraping import fetch_html, parse_html

logger = logging.getLogger("apollo.pipeline")

# Text SoundCloud's own error page uses when a playlist/profile requires being
# logged in as its owner — used to turn a silent "0 tracks" into a clear error.
_LOGIN_REQUIRED_MARKER = "may have to log in to view this playlist"

# Both fetch_html/discover_playlists drive a real headless browser to whatever
# URL they're given — without this check, that's an open SSRF primitive
# (internal network probing, cloud metadata endpoints, etc.), especially once
# reachable outside localhost or fed from a URL list (see ingest.py).
_ALLOWED_HOSTS = {"soundcloud.com"}


class DisallowedHostError(Exception):
    """Raised for a URL outside _ALLOWED_HOSTS."""


class LoginRequiredError(Exception):
    """Raised when SoundCloud's page says this requires being logged in as its owner."""


class FetchError(Exception):
    """Raised when the headless browser fails to load the page."""


class LakeWriteError(Exception):
    """Raised when writing the raw scrape to the data lake fails."""


def is_allowed_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in _ALLOWED_HOSTS or host.endswith(".soundcloud.com")


async def scrape_and_store(url: str) -> dict:
    """Fetch -> parse -> land in the lake -> upsert into the warehouse for one
    URL. This is the single source of truth for that sequence, shared by
    POST /scrape (main.py, one URL per HTTP request) and the scheduled ingest
    CLI (ingest.py, a fixed list of URLs run by the k8s CronJob) — callers
    just need to translate the exceptions below into whatever's appropriate
    for them (an HTTP status, a log line and move to the next URL, etc.)."""
    if not is_allowed_host(url):
        raise DisallowedHostError(url)

    logger.info("Scrape requested for %s", url)

    fetch_start = time.monotonic()
    try:
        html, hydration = await fetch_html(url)
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed error for callers
        raise FetchError(str(exc)) from exc
    fetch_ms = (time.monotonic() - fetch_start) * 1000
    logger.debug(
        "Fetched %s in %.0fms (%d bytes html, hydration=%s)",
        url, fetch_ms, len(html), "present" if hydration else "absent",
    )

    parse_start = time.monotonic()
    tracks = parse_html(html, hydration, source_url=url)
    parse_ms = (time.monotonic() - parse_start) * 1000
    logger.debug("Parsed %d tracks from %s in %.1fms", len(tracks), url, parse_ms)

    if not tracks and _LOGIN_REQUIRED_MARKER in html:
        logger.warning("Scrape of %s blocked by a login wall", url)
        raise LoginRequiredError(url)

    scraped_at = datetime.now(timezone.utc)

    # 1. Land the raw scrape in the data lake first — this is the durable,
    #    replayable record, independent of whatever the warehouse schema looks like today.
    lake_start = time.monotonic()
    try:
        lake_key = lake.put_raw_scrape(url, tracks, scraped_at=scraped_at)
    except Exception as exc:  # noqa: BLE001
        raise LakeWriteError(str(exc)) from exc
    lake_ms = (time.monotonic() - lake_start) * 1000

    # 2. Load the parsed rows into the warehouse for querying.
    warehouse_start = time.monotonic()
    warehouse.load_tracks(tracks, source_url=url, lake_object_key=lake_key, scraped_at=scraped_at)
    warehouse_ms = (time.monotonic() - warehouse_start) * 1000

    total_ms = fetch_ms + parse_ms + lake_ms + warehouse_ms
    logger.info(
        "Scraped %d tracks from %s in %.0fms total "
        "(fetch=%.0fms parse=%.1fms lake=%.1fms warehouse=%.1fms) -> %s",
        len(tracks), url, total_ms, fetch_ms, parse_ms, lake_ms, warehouse_ms, lake_key,
    )

    return {
        "source_url": url,
        "scraped_at": scraped_at,
        "track_count": len(tracks),
        "lake_object_key": lake_key,
        "tracks": tracks,
    }
