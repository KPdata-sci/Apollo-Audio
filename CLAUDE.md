# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A dockerized SoundCloud playlist/profile scraper: FastAPI + Playwright app
(`scraper/`) that scrapes SoundCloud, lands raw results in a filesystem data
lake, then upserts parsed tracks into a Postgres warehouse. The single-page
vanilla-JS front end (scrape, browse a profile's playlists, play via
SoundCloud's own embed widget, download only when the artist enabled it) is a
**separate** deployable (`frontend/`, nginx serving `scraper/app/static/index.html`)
— the API no longer mounts or serves it. They talk over the network
(`window.APOLLO_API_BASE` + CORS), not same-origin. See `docs/HOSTING.md` for
the Kubernetes/Tailscale deployment this split was built for, and
`infra/terraform-k8s/` for the manifests.

## Commands

Run the whole stack:
```bash
cp .env.example .env      # first time only
docker compose up --build
```
UI: http://localhost:8080 (`frontend`, nginx). API: http://localhost:8000 (`api`, `/docs` for Swagger). Adminer: :8081. Postgres: :5432.

Run tests (they're excluded from the built image via `scraper/.dockerignore`,
so copy them into the running container rather than rebuilding):
```bash
docker compose exec -T api rm -rf /app/tests   # clear any stale copy first — `cp` into an
                                                 # existing dir nests it and doubles test collection
docker compose cp scraper/tests api:/app/tests
docker compose exec -T api sh -c "pip install -q pytest httpx && cd /app && python -m pytest tests -q"
```
Single test: append `::test_name` to the `pytest tests -q` invocation, e.g. `pytest tests/test_scraping.py::test_parse_playlist_markup_no_hydration -q`.

Local dev without Docker:
```bash
cd scraper
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest httpx
playwright install firefox
uvicorn app.main:app --reload   # or: pytest
```

No linter/formatter is configured in this repo (no pyproject.toml, no ruff/flake8 config) — don't assume one.

Rebuild after changing `scraper/` code: `docker compose up -d --build api`. After changing `scraper/app/static/index.html`, rebuild `frontend` instead (it's a separate container now, see "Architecture" below).

## Architecture

**Pipeline**: `POST /scrape` → Playwright fetches + scrolls the page →
`parse_html()` extracts tracks → `lake.put_raw_scrape()` writes immutable
timestamped JSON (durable, replayable record) → `warehouse.load_tracks()`
upserts into Postgres `tracks`, deduped on track `url` (not `artist`+`title`+`url`
— artist attribution can legitimately improve between scrapes, so it must not
be part of the conflict key or re-scrapes create duplicates instead of updating).

**The non-obvious core of `scraping.py`**: SoundCloud's SSR payload
(`window.__sc_hydration`, read from the static HTML) only fully hydrates the
first handful of tracks in a playlist — the rest are id-only stubs. Reading
that *same* object via `page.evaluate()` **after scrolling** gets every track
fully hydrated instead, because scrolling triggers SoundCloud's own app to
lazy-load the rest into its live in-page state. This is why `fetch_html()`
returns both `html` and `hydration` separately, and why `hydration` must come
from `page.evaluate()`, never from regex/BeautifulSoup on the HTML string.

**Parse priority in `parse_html()`**: DOM/CSS parsing (`_parse_dom`) is the
base layer — it reliably gets title+url for every track even when nothing
else does. Hydration data enriches artist/genre/downloadable on top of that
when a matching url is found. If DOM parsing finds *nothing* (unrecognized
page layout), it falls back to hydration-only records. If neither DOM nor
hydration gives an artist for a track (typical on profile/stream pages, which
expose no per-track hydration at all), `_hydration_profile_owner()` attributes
it to the profile being scraped — but only when the track's own permalink URL
confirms that account is really the uploader, so a repost from someone else's
account in the stream isn't mislabeled. Canonicalize URLs (`_canonical_url`,
strips tracking query params like `?in=`) before comparing across DOM/hydration
sources or against the warehouse — otherwise the same track looks different
depending on where it was linked from.

**Playback/download is a deliberate policy boundary, not just a feature
choice**: playback streams through SoundCloud's own embeddable player
(`w.soundcloud.com/player`), never downloads or proxies audio. A download
link is shown *only* when SoundCloud's own data says `downloadable: true` for
that specific track, and even then it links to the track's SoundCloud page
rather than serving a file. Don't build a stream-URL-resolving downloader —
that was a deliberate choice, not an oversight.

**Config** (`settings.py`): `pydantic-settings` `BaseSettings`, all env vars
prefixed `APOLLO_`. Notable ones: `APOLLO_LAKE_BACKEND` (`filesystem` default,
or `s3` for MinIO/real S3 via the same interface in `lake.py`),
`APOLLO_SOUNDCLOUD_COOKIES` (opt-in, user-supplied session cookie for
login-gated pages like a personal Discover Weekly — untested, no test account
was available; the app returns a `422` with a clear message on those pages
rather than a confusing empty result).

**Logging** (`logging_config.py`): every request gets a short id via a
`ContextVar`, injected into *all* log records through a `LogRecordFactory` —
not a `logging.Filter`, because a Filter attached to the `"apollo"` logger
never fires for child loggers like `"apollo.scraping"` (filters only run on
the exact logger they're attached to, not descendants; this was a real bug
here before the fix). File logs rotate at `APOLLO_LOG_MAX_BYTES` and gzip via
a custom `rotator`/`namer` pair — the stdlib cookbook version of this
double-compresses backups as they shift down slots (`.2.gz` re-gzipped into
`.3.gz`), so the rotator here checks the gzip magic bytes and moves
already-compressed files instead of re-wrapping them.

**Front end** (`scraper/app/static/index.html`): single file, no build step,
no framework. Served by the separate `frontend/` nginx image, **not** mounted
on the FastAPI app — `main.py` is a pure JSON API now (CORS via
`APOLLO_CORS_ORIGINS`, no `StaticFiles`). The page reads the API's address
from `window.APOLLO_API_BASE`, set at container start by
`frontend/40-apollo-config.sh` from the `API_BASE_URL` env var — empty means
"same origin," which only the old combined setup relied on. `POST /scrape`
and `POST /api/discover-playlists` go through `require_api_key` (`main.py`),
a no-op unless `APOLLO_API_KEY` is set — see `docs/HOSTING.md` for why this
is a deterrent, not real auth.

**Playlist catalog** (`playlists.py`): ships with an empty `CATALOG` dict by
design — no third-party or personal SoundCloud accounts are baked into this
repo. It's read fresh on every `GET /api/playlists` call.

**`docker-compose.yml`**: `COMPOSE_PROJECT_NAME` is pinned in `.env`. If this
project's directory ever gets renamed or moved, keep that pin — otherwise
Compose derives a different project name from the new folder name and spins
up a brand-new empty Postgres volume instead of reusing the existing one.

**Two separate Terraform trees under `infra/`** — don't conflate them:
`terraform-aws/` is an unfinished, non-functional AWS sketch (kept for
possible future reference only). `terraform-k8s/` is real and
`terraform validate`-checked against the Kubernetes provider, for deploying
to a k3s host — but never `terraform apply`'d anywhere yet.

## Known rough edges (see README "Known limitations" for the full list)

- CSS selectors in `scraping.py` will break silently on a SoundCloud
  redesign — a `track_count: 0` response with a "selectors may be stale"
  warning in the logs is the signal to check them.
- No auth on the API or Adminer — local-only stack as shipped; see
  `docs/PUBLIC_ACCESS_DESIGN.md` before exposing it anywhere.
- `docs/CRAWLER_DESIGN.md` documents a planned multi-page crawler/index —
  only single-profile playlist discovery (`discover_playlists()`) is built.

## Filesystem quirks if working from this repo's actual location

This project lives on an exFAT-formatted USB drive. macOS shadows every file
there with a `._*` AppleDouble sidecar carrying xattrs exFAT can't store
natively. These have caused real failures, not just clutter: `docker build`
aborts outright if one exists in the build context (`operation not
permitted`). If a build fails with an xattr error, run:
```bash
find . -name '._*' -delete
```
`scraper/.dockerignore` excludes `._*` from the build context, but files
created *after* the last build can still trip the context-scanning step
before ignore rules apply — deleting them is the actual fix, `.dockerignore`
alone isn't sufficient.

The `testing/`, `0.0.1av/`, `DB/`, and `iterm/` directories are pre-rewrite
drafts and one unrelated third-party clone — superseded by `scraper/` and
`infra/terraform-aws/`, gitignored rather than deleted, not part of the live
app. Don't treat anything in them as current.
