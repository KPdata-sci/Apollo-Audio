import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from . import lake, playlists, warehouse
from .logging_config import configure_logging, request_id_var
from .models import (
    DiscoveredPlaylists,
    DiscoverPlaylistsRequest,
    PlaylistEntry,
    ScrapeRequest,
    ScrapeResult,
    TracksPage,
)
from .scraping import discover_playlists, fetch_html, parse_html

STATIC_DIR = Path(__file__).parent / "static"

configure_logging()
logger = logging.getLogger("apollo.main")

# Text SoundCloud's own error page uses when a playlist/profile requires being
# logged in as its owner — used to turn a silent "0 tracks" into a clear error.
_LOGIN_REQUIRED_MARKER = "may have to log in to view this playlist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    lake.ensure_bucket()
    logger.info("Startup complete — lake backend ready")
    yield


app = FastAPI(
    title="Project Apollo — SoundCloud Scraper API",
    description=(
        "Scrapes SoundCloud playlists/profiles, lands the raw result in a data "
        "lake, then loads it into a Postgres data warehouse. See /docs for the "
        "interactive reference, or docs/API.md in the repo for a plain-text one."
    ),
    version="0.3.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # A short id shared by every log line emitted while handling this request,
    # across every module (apollo.main, apollo.scraping, apollo.warehouse,
    # apollo.lake) — makes `grep <id> logs/apollo.log` pull the whole story of
    # one scrape instead of you having to correlate timestamps by hand.
    token = request_id_var.set(uuid.uuid4().hex[:8])
    start = time.monotonic()
    logger.debug("-> %s %s from %s", request.method, request.url.path, request.client.host if request.client else "-")
    try:
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s -> %d (%.0fms)", request.method, request.url.path, response.status_code, duration_ms
        )
        return response
    except Exception:
        logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
        raise
    finally:
        request_id_var.reset(token)


@app.get("/health", tags=["meta"], summary="Liveness check")
def health() -> dict:
    """Returns 200 with `{"status": "ok"}` if the API process is up. Does not
    check Postgres/lake connectivity — use it for container health checks."""
    return {"status": "ok"}


@app.post(
    "/scrape",
    response_model=ScrapeResult,
    tags=["scrape"],
    summary="Scrape a SoundCloud playlist, set, or profile",
)
async def scrape(request: ScrapeRequest) -> ScrapeResult:
    """Fetches the given SoundCloud URL with a headless browser, scrolls it to
    trigger SoundCloud's own lazy-loading, extracts the track list (title,
    artist, genre, url, downloadable), lands the raw result in the data lake,
    then upserts it into the warehouse `tracks` table (deduped by track url).

    Works on playlist/set pages and user profile pages. Pages that require
    being logged in as a specific SoundCloud account (e.g. a personal
    "Discover Weekly") will fail with a 422 unless `APOLLO_SOUNDCLOUD_COOKIES`
    is configured — see .env.example.
    """
    url = str(request.url)
    logger.info("Scrape requested for %s", url)

    fetch_start = time.monotonic()
    try:
        html, hydration = await fetch_html(url)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a 502
        logger.exception("Failed to fetch %s", url)
        raise HTTPException(status_code=502, detail=f"Failed to fetch page: {exc}") from exc
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
        raise HTTPException(
            status_code=422,
            detail=(
                "SoundCloud says this page requires being logged in as its owner. "
                "Set APOLLO_SOUNDCLOUD_COOKIES in your .env to your own session "
                "cookies to try scraping it (see .env.example)."
            ),
        )

    scraped_at = datetime.now(timezone.utc)

    # 1. Land the raw scrape in the data lake first — this is the durable,
    #    replayable record, independent of whatever the warehouse schema looks like today.
    lake_start = time.monotonic()
    lake_key = lake.put_raw_scrape(url, tracks, scraped_at=scraped_at)
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

    return ScrapeResult(
        source_url=url,
        scraped_at=scraped_at,
        track_count=len(tracks),
        lake_object_key=lake_key,
        tracks=tracks,
    )


@app.get(
    "/api/tracks",
    response_model=TracksPage,
    tags=["warehouse"],
    summary="List scraped tracks from the warehouse",
)
def list_tracks(search: str = "", limit: int = 50, offset: int = 0) -> TracksPage:
    """Paginated, searchable read of the `tracks` table. `search` matches
    (case-insensitively) against artist or title. `limit` is clamped to
    1-200."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    rows, total = warehouse.list_tracks(search=search.strip(), limit=limit, offset=offset)
    return TracksPage(items=rows, total=total, limit=limit, offset=offset)


@app.post(
    "/api/discover-playlists",
    response_model=DiscoveredPlaylists,
    tags=["catalog"],
    summary="Browse a profile's playlists without scraping them",
)
async def discover_playlists_endpoint(request: DiscoverPlaylistsRequest) -> DiscoveredPlaylists:
    """Fetches the given profile's `/sets` page (its playlist index) and
    returns every playlist listed there — a read-only browse step, separate
    from scraping. Nothing is written to the lake or warehouse here; use the
    returned urls with POST /scrape for whichever ones you actually want."""
    profile_url = str(request.profile_url)
    logger.info("Discovering playlists for %s", profile_url)

    try:
        found = await discover_playlists(profile_url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to discover playlists for %s", profile_url)
        raise HTTPException(status_code=502, detail=f"Failed to fetch profile: {exc}") from exc

    logger.info("Found %d playlists for %s", len(found), profile_url)
    return DiscoveredPlaylists(profile_url=profile_url, playlists=found)


@app.get(
    "/api/playlists",
    response_model=dict[str, list[PlaylistEntry]],
    tags=["catalog"],
    summary="List the curated genre -> playlist catalog",
)
def list_playlist_catalog() -> dict[str, list[PlaylistEntry]]:
    """Returns the hand-curated `{genre: [{name, url, note}]}` catalog used to
    populate the front end's genre/playlist dropdowns. Edit
    scraper/app/playlists.py to add your own entries — no migration needed."""
    return playlists.list_playlists()


# Mounted last so it only catches paths the routes above didn't — serves the
# front end at "/" and its assets, without shadowing the API endpoints.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
