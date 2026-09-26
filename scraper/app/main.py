import hashlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import lake, playlists, warehouse
from .logging_config import configure_logging, request_id_var
from .models import (
    DiscoveredPlaylists,
    DiscoverPlaylistsRequest,
    FavoriteResult,
    PlaylistEntry,
    ScrapeRequest,
    ScrapeResult,
    TracksPage,
    WarehouseStats,
)
from .pipeline import (
    DisallowedHostError,
    FetchError,
    LakeWriteError,
    LoginRequiredError,
    is_allowed_host,
    scrape_and_store,
)
from .scraping import discover_playlists
from .settings import settings

configure_logging()
logger = logging.getLogger("apollo.main")


def _require_soundcloud_host(url: str) -> None:
    if not is_allowed_host(url):
        raise HTTPException(status_code=422, detail="Only soundcloud.com URLs are allowed.")


def _reject_nul(**params: str) -> None:
    """Postgres rejects NUL in text values outright, so without this a stray
    %00 in any free-text query param surfaces as an unhandled 500 from
    psycopg instead of a client error. Named as a validator (not an inline
    per-endpoint loop) so a future free-text param picks it up by adding one
    keyword argument here, not by remembering to re-derive this check."""
    for name, value in params.items():
        if "\x00" in value:
            raise HTTPException(status_code=422, detail=f"`{name}` must not contain NUL characters.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    lake.ensure_bucket()
    if not settings.api_key:
        logger.warning(
            "APOLLO_API_KEY is not set — POST /scrape and POST /api/discover-playlists "
            "are unauthenticated. Set APOLLO_API_KEY before this API is reachable "
            "outside a fully trusted network (see docs/HOSTING.md)."
        )
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

# The catalog only changes on redeploy, so browsers may reuse it for an hour
# without asking. Everything else is revalidated every load: the browser sends
# If-None-Match and gets a body-less 304 when the data hasn't changed, so the
# library stays exactly current after a scrape while repeat loads stay cheap
# (this matters on a phone over a relayed Tailscale link).
_CACHE_POLICIES = {"/api/playlists": "public, max-age=3600"}


# Registered before CORSMiddleware so CORS wraps it and 304s still carry the
# CORS headers a cross-origin fetch needs.
@app.middleware("http")
async def etag_cache(request: Request, call_next):
    response = await call_next(request)
    if (
        request.method != "GET"
        or not request.url.path.startswith("/api/")
        or response.status_code != 200
        or not response.headers.get("content-type", "").startswith("application/json")
    ):
        return response

    body = b"".join([chunk async for chunk in response.body_iterator])
    # This still runs the full handler (including any DB query) on every
    # request — a 304 only saves the response bytes on the wire, not the
    # server-side work, so blake2b (cache validation, not security) is
    # plenty; weak because GZipMiddleware may re-encode the body on the way out.
    etag = f'W/"{hashlib.blake2b(body, digest_size=16).hexdigest()}"'
    headers = {"ETag": etag, "Cache-Control": _CACHE_POLICIES.get(request.url.path, "no-cache")}
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)
    return Response(content=body, status_code=200, headers={**dict(response.headers), **headers})


# Only relevant once the front end is served from a different origin (see
# frontend/) — same-origin requests (the old combined docker-compose setup)
# never hit CORS checks at all. "*" is fine here because these endpoints don't
# use cookies/session auth; the write endpoints have their own gate below.
_cors_origins = ["*"] if settings.cors_origins.strip() == "*" else [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
# JSON like the catalog (~12KB) compresses ~5x; small responses aren't worth it.
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Each /scrape call drives a full headless browser — cheap to trigger, costly
# to run. Per-IP limits (keyed by X-API-Key when set, since a shared tailnet
# egress can otherwise put many people behind one IP) stop a runaway client
# (or naive abuse) from queuing up concurrent scrapes.
limiter = Limiter(key_func=lambda request: request.headers.get("x-api-key") or get_remote_address(request))
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Gate for endpoints that trigger real work (scraping/browsing SoundCloud).
    A no-op when APOLLO_API_KEY isn't set, matching this app's behavior before
    this setting existed — set it once this API is reachable outside a trusted
    network. Read endpoints (/api/tracks, /api/stats, /api/playlists) are never gated."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")


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
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("10/minute")
async def scrape(request: Request, payload: ScrapeRequest) -> ScrapeResult:
    """Fetches the given SoundCloud URL with a headless browser, scrolls it to
    trigger SoundCloud's own lazy-loading, extracts the track list (title,
    artist, genre, url, downloadable), lands the raw result in the data lake,
    then upserts it into the warehouse `tracks` table (deduped by track url).

    Works on playlist/set pages and user profile pages. Pages that require
    being logged in as a specific SoundCloud account (e.g. a personal
    "Discover Weekly") will fail with a 422 unless `APOLLO_SOUNDCLOUD_COOKIES`
    is configured — see .env.example.
    """
    url = str(payload.url)
    try:
        result = await scrape_and_store(url)
    except DisallowedHostError as exc:
        raise HTTPException(status_code=422, detail="Only soundcloud.com URLs are allowed.") from exc
    except LoginRequiredError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "SoundCloud says this page requires being logged in as its owner. "
                "Set APOLLO_SOUNDCLOUD_COOKIES in your .env to your own session "
                "cookies to try scraping it (see .env.example)."
            ),
        ) from exc
    except FetchError as exc:
        logger.exception("Failed to fetch %s", url)
        raise HTTPException(status_code=502, detail=f"Failed to fetch page: {exc}") from exc
    except LakeWriteError as exc:
        logger.exception("Failed to write raw scrape to the lake for %s", url)
        raise HTTPException(status_code=502, detail="Failed to write scrape result to the data lake") from exc

    return ScrapeResult(**result)


@app.get(
    "/api/tracks",
    response_model=TracksPage,
    tags=["warehouse"],
    summary="List scraped tracks from the warehouse",
)
def list_tracks(
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    genre: str = "",
    source_url: str = "",
    sort: Literal["recent", "artist", "title", "popular"] = "recent",
    favorited_only: bool = False,
) -> TracksPage:
    """Paginated, searchable, filterable read of the `tracks` table.

    - `search`: case-insensitive literal substring match against artist or
      title (`%` and `_` are matched literally, not as wildcards).
    - `genre`: case-insensitive match on the trimmed genre; every `genre`
      value returned by GET /api/stats round-trips here. Empty = no filter.
    - `source_url`: exact match on the scraped page url. Empty = no filter.
    - `sort`: `recent` (default, newest scrape first), `artist`, `title`
      (both A-Z, case-insensitive), or `popular` (highest `playback_count`
      first, tracks with none known sort last). Anything else is a 422.
    - `favorited_only`: only tracks favorited via POST /api/tracks/{id}/favorite.
    - `limit` is clamped to 1-200; `total` is the count after all filters.
    - A NUL character in `search`, `genre`, or `source_url` is a 422.
    """
    _reject_nul(search=search, genre=genre, source_url=source_url)

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    rows, total = warehouse.list_tracks(
        search=search.strip(),
        limit=limit,
        offset=offset,
        # Emptiness is judged on the stripped value, but a non-empty genre is
        # passed through untouched — the SQL does the trimming, identically on
        # both sides of the comparison.
        genre=genre if genre.strip() else "",
        source_url=source_url.strip(),
        sort=sort,
        favorited_only=favorited_only,
    )
    return TracksPage(items=rows, total=total, limit=limit, offset=offset)


@app.post(
    "/api/tracks/{track_id}/favorite",
    response_model=FavoriteResult,
    tags=["favorites"],
    summary="Favorite a track",
    dependencies=[Depends(require_api_key)],
)
def favorite_track(track_id: int) -> FavoriteResult:
    """Adds `track_id` to the shared favorites list (this app has no user
    accounts, so it's one list rather than per-person). Idempotent — favoriting
    an already-favorited track just returns the same result. 404 if no track
    with this id exists."""
    if not warehouse.add_favorite(track_id):
        raise HTTPException(status_code=404, detail=f"No track with id {track_id}")
    return FavoriteResult(id=track_id, favorited=True)


@app.delete(
    "/api/tracks/{track_id}/favorite",
    response_model=FavoriteResult,
    tags=["favorites"],
    summary="Un-favorite a track",
    dependencies=[Depends(require_api_key)],
)
def unfavorite_track(track_id: int) -> FavoriteResult:
    """Removes `track_id` from the shared favorites list. Idempotent — 404
    only when no track with this id exists at all, not when it simply wasn't
    favorited to begin with."""
    if not warehouse.remove_favorite(track_id):
        raise HTTPException(status_code=404, detail=f"No track with id {track_id}")
    return FavoriteResult(id=track_id, favorited=False)


@app.get(
    "/api/stats",
    response_model=WarehouseStats,
    tags=["warehouse"],
    summary="Warehouse overview: totals, genre facets, and scraped sources",
)
def warehouse_stats() -> WarehouseStats:
    """Read-only summary of the `tracks` table.

    - `total_tracks`, `total_sources` (distinct `source_url`s), `total_favorites`, and
      `last_scraped_at` (null when the warehouse is empty).
    - `genres`: up to 40, grouped case-insensitively on the trimmed genre,
      null/blank excluded, sorted by count desc then name. The displayed
      `genre` is the group's most common trimmed spelling (ties broken by
      byte order, so "Piano" beats "piano"), and always round-trips as the
      `genre` filter on GET /api/tracks, returning exactly `count` tracks.
      Hashtag-style values (containing `#`, i.e. uploader tag spam rather
      than a genre) are omitted from this list but remain filterable.
    - `sources`: up to 100 scraped pages with their track count and latest
      scrape time, most recently scraped first.
    """
    return WarehouseStats(**warehouse.get_stats(genre_limit=40, source_limit=100))


@app.post(
    "/api/discover-playlists",
    response_model=DiscoveredPlaylists,
    tags=["catalog"],
    summary="Browse a profile's playlists without scraping them",
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("20/minute")
async def discover_playlists_endpoint(request: Request, payload: DiscoverPlaylistsRequest) -> DiscoveredPlaylists:
    """Fetches the given profile's `/sets` page (its playlist index) and
    returns every playlist listed there — a read-only browse step, separate
    from scraping. Nothing is written to the lake or warehouse here; use the
    returned urls with POST /scrape for whichever ones you actually want."""
    profile_url = str(payload.profile_url)
    _require_soundcloud_host(profile_url)
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
    """Returns the curated, verified `{genre: [{name, url, note}]}` catalog
    behind the front end's Discover view. Edit scraper/app/playlists.py to
    change it — no migration needed."""
    return playlists.list_playlists()
