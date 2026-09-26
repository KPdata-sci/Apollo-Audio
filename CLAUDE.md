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
This exact sequence lives in `pipeline.py::scrape_and_store()`, shared by the
HTTP endpoint and `ingest.py` (see below) — don't duplicate it in a third
place if you add another entry point.

**Scheduled ingest** (`ingest.py`): re-runs `scrape_and_store()` against a
fixed, hand-configured URL list (`APOLLO_INGEST_URLS`) instead of one ad-hoc
request — for keeping a small set of playlists fresh without opening the UI.
Deliberately **not** a crawler (no discovery, no recursion, the URL list only
changes when a person edits it) — see `docs/CRAWLER_DESIGN.md`'s closing
section for why that distinction matters for SoundCloud ToS/courtesy. Runs
via `docker compose run --rm api python -m app.ingest` locally, or a
Kubernetes `CronJob` (`infra/terraform-k8s/ingest-cronjob.tf`) on a schedule.
One bad URL logs and moves on rather than aborting the batch.

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
`APOLLO_CORS_ORIGINS`, no `StaticFiles`). `frontend/40-apollo-config.sh`
writes `config.js` at container start with `APOLLO_API_BASE` (explicit
override, normally empty) and `APOLLO_API_PORT`. With no override, the page
calls the API at *its own* `location.hostname` on that port. That's
deliberate: the same deployment is reached via LAN IP, Tailscale IP or
localhost, and a single baked-in address only works for one of them (this
was a real bug). `POST /scrape` and `POST /api/discover-playlists` go through
`require_api_key` (`main.py`), a no-op unless `APOLLO_API_KEY` is set — see
`docs/HOSTING.md` for why this is a deterrent, not real auth.

The UI has three hash-routed views: Library (reads `GET /api/stats` for
headline numbers and genre/source facets, and `GET /api/tracks` with
`genre`/`source_url`/`sort` filters), Discover (the catalog) and Add (scrape by
URL, browse a profile). Every scrape goes through one in-page queue, one at a
time, which waits and retries on 429. The docked player's play/pause state
comes from the SoundCloud widget's own postMessage events rather than being
assumed. On iOS, autoplay in the iframe is blocked, so the player shows
"Press ▶" instead of pretending to play. There's still no auto-advance:
playback is one track per explicit tap, by policy.

**Playlist catalog** (`playlists.py`): a curated, verified list of public
SoundCloud playlists across 22 genres (populated 2026-09-25 at the owner's
request — it used to ship empty; extended 2026-09-26 with violin/strings,
baroque/classical and film-score genres), mostly from SoundCloud's own
editorial accounts. Every entry was checked with the real
`fetch_html`/`parse_html`, and the comment block in the file shows how to
re-verify. SoundCloud playlists do vanish or change, so re-verify before
trusting it long-term.
`tests/test_playlists.py` guards its shape: soundcloud.com only, no
duplicates, profiles carry a `note`. It's read fresh on every
`GET /api/playlists` call.

**Warehouse queries** (`warehouse.py`): the `sort` values map through a
whitelist to fixed SQL, and are never interpolated. `search` is a literal
substring match (`escape_like` + `ESCAPE '\'`), so `%`/`_` aren't wildcards.
NUL bytes in query params are rejected with 422, because Postgres would
otherwise 500. `/api/stats` groups genres by `lower(btrim(genre))` and leaves
out blanks and `#`-hashtag spam. Every genre it returns must round-trip as
`/api/tracks?genre=` with the same count. `tests/test_warehouse_integration.py`
checks this read-only against a real DB, and skips when none is reachable.

**`docker-compose.yml`**: `COMPOSE_PROJECT_NAME` is pinned in `.env`. If this
project's directory ever gets renamed or moved, keep that pin — otherwise
Compose derives a different project name from the new folder name and spins
up a brand-new empty Postgres volume instead of reusing the existing one.

**Two separate Terraform trees under `infra/`** — don't conflate them:
`terraform-aws/` is an unfinished, non-functional AWS sketch (kept for
possible future reference only). `terraform-k8s/` is real and
`terraform validate`-checked against the Kubernetes provider, for deploying
to a k3s host — including a `CronJob` for scheduled ingest
(`infra/terraform-k8s/ingest-cronjob.tf`, see "Scheduled ingest" above).

**CI** (`.github/workflows/ci.yml`): runs on every push/PR — the test suite
against a real `postgres:16-alpine` service container (not mocked, so
`test_warehouse_integration.py`'s DB-dependent tests actually run), `terraform
fmt`/`validate` for `terraform-k8s` (`terraform-aws` is checked too but
`continue-on-error: true`, since its own README documents it as an unfinished,
known-broken sketch), and a build of both Docker images as a smoke test (no
push). CD — actually rolling this out to the k3s VM — stays a manual,
documented step (see `docs/CI_CD.md`) because GitHub-hosted runners can't
reach a Tailscale-only host.

## Known rough edges (see README "Known limitations" for the full list)

- CSS selectors in `scraping.py` will break silently on a SoundCloud
  redesign — a `track_count: 0` response with a "selectors may be stale"
  warning in the logs is the signal to check them.
- No auth on the API or Adminer — local-only stack as shipped; see
  `docs/PUBLIC_ACCESS_DESIGN.md` before exposing it anywhere.
- `docs/CRAWLER_DESIGN.md` documents a planned multi-page crawler/index —
  only single-profile playlist discovery (`discover_playlists()`) is built.
- `docs/EDGE_SECURITY.md`'s top finding is unresolved: the k3s VM's bridged
  networking exposes the NodePorts (30800/30880) to every device on the LAN,
  not just Tailscale peers — Tailscale ACLs only govern the tailnet
  interface, they don't firewall the LAN-facing one.

## Developing from Windows (this repo's actual location)

This repo is developed from a Windows PC (`E:\ApolloAudio`, an internal NTFS
drive — not a Mac). Two Windows-specific things that have actually caused
failures here, not just style points:
- **Git Bash / MSYS path mangling**: Git Bash auto-converts arguments that
  look like absolute POSIX paths before handing them to the process, which
  silently corrupts `docker run ... -w /app ...`-style container paths (they
  get rewritten to a Windows path). Prefix such commands with
  `MSYS_NO_PATHCONV=1`, e.g.
  `MSYS_NO_PATHCONV=1 docker run --rm -v "E:\ApolloAudio\scraper:/app" -w /app apollo-api:latest ...`.
- **Two shells, two syntaxes**: commands here run under either Git Bash
  (POSIX `sh`) or PowerShell — they are not interchangeable (`$VAR` vs
  `$env:VAR`, `/dev/null` vs `$null`, quoting rules). Match the syntax to
  whichever shell is actually invoking the command.

The `testing/`, `0.0.1av/`, `DB/`, and `iterm/` directories are pre-rewrite
drafts and one unrelated third-party clone — superseded by `scraper/` and
`infra/terraform-aws/`, gitignored rather than deleted, not part of the live
app. Don't treat anything in them as current.
