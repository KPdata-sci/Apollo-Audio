# Project Apollo — SoundCloud Scraper

A dockerized SoundCloud playlist/profile scraper with a local data lake and
data warehouse (Postgres), a front end to scrape/browse/play tracks, and no
cloud account required.

## Architecture

```
   +-----------+   fetch()/CORS    +---------------+
   | frontend  | ----------------> |  FastAPI app  |  (scraper/, Playwright + BeautifulSoup)
   | (nginx)   |                   +---------------+
   +-----------+                      |          |
                                       v          v
                                  +-----------+  +----------+
                                  | ./data/   |  | Postgres |
                                  | lake/     |->| (wareh.) |
                                  +-----------+  +----------+
                                  raw JSON       tracks table
                                  landing        (queryable)
```

The API (`scraper/`) is a standalone JSON service — no UI is mounted on it.
The front end (`frontend/`, same `scraper/app/static/index.html`, served by
nginx) is a separate container that talks to the API over the network. This
split matters once you deploy them independently (see
[docs/HOSTING.md](docs/HOSTING.md) for the Kubernetes/Tailscale setup) — for
local `docker compose up`, both still come up together and reach each other
over `localhost`.

Every scrape is written to the **data lake** first as an immutable, timestamped
raw JSON object — this is the durable record you can always replay from. It is
then parsed and upserted into the **data warehouse** (Postgres `tracks` table)
for querying.

By default the lake is a bind-mounted local directory (`./data/lake`) written
via [scraper/app/lake.py](scraper/app/lake.py) — no extra container needed, and
you can browse the raw JSON files directly in Finder/VS Code. That file also
has an `S3Lake` backend (MinIO/real AWS S3) behind the same interface — set
`APOLLO_LAKE_BACKEND=s3` once you have an S3-compatible endpoint to point at.
It isn't in `docker-compose.yml` by default because this machine's Docker
registry proxy only allows official Docker Hub images and denies `minio/minio`
(`pull access denied ... repository does not exist or may require 'docker
login'`) — either get that image allowlisted, or point `APOLLO_S3_ENDPOINT_URL`
at any S3-compatible endpoint you do have access to.

## Running it

```bash
cp .env.example .env
docker compose up --build
```

This starts:

| Service    | URL                          | Purpose                        |
|------------|-------------------------------|---------------------------------|
| frontend   | http://localhost:8080        | Front end — scrape + browse tracks |
| api        | http://localhost:8000        | The scraper API |
| api        | http://localhost:8000/docs  | FastAPI + Swagger UI            |
| ./data/lake | (local folder)               | Data lake — raw scraped JSON    |
| postgres   | localhost:5432                 | Data warehouse                  |
| adminer    | http://localhost:8081         | Postgres UI (system: PostgreSQL, server: `postgres`) |

### Using the front end

Open [localhost:8080](http://localhost:8080). It's built for phones first, and
has three views. On desktop you switch between them with the header switcher;
on phones, with the bottom tab bar.
- **Discover:** genre tiles and playlist cards from the curated catalog in
  [scraper/app/playlists.py](scraper/app/playlists.py). That's about 19
  genres of public playlists, each checked with the real scraper when added.
  Tap Scrape on a card, or "Scrape all" for a whole genre.
- **Add:** paste any playlist, set or profile URL. Or browse a profile's
  `/sets` page to list its playlists first. Browsing is read-only and never
  scrapes on its own.
- **Library:** everything in the warehouse. It has headline stats (including
  a Favorites count), a debounced search (press `/` to focus), genre chips
  with counts, a source filter, a Favorites-only toggle, sorting (including
  "Most played", by SoundCloud's own play count) and paging. Every track row
  shows its own artwork (or the uploader's avatar, when a track has none of
  its own) hotlinked straight from SoundCloud's CDN — this app never
  downloads or rehosts it, same policy as audio itself — and has a heart
  button to favorite it: your own personal like-list, once you log in (see
  "Logging in" below). It reads `GET /api/stats` and
  `GET /api/tracks?search=&genre=&source_url=&sort=&favorited_only=`.

### Logging in

Favoriting a track is the one thing in this app that's personal rather than
shared — everything else (browsing, scraping, stats) works the same for
everyone with no login at all. There's no public sign-up: an account is
created for you by whoever runs the deployment, via
`docker compose exec api python -m app.create_user <username>` (prompts for
a password). Log in from the header once you have one, and your like-list
follows you across devices/browsers as long as you're logged in on each.
Passwords are hashed (Argon2id) before they ever reach the database — see
[CLAUDE.md](CLAUDE.md)'s Authentication section for the full model.

Every scrape goes through one queue, one at a time. The strip under the
header shows what's running, the elapsed time and how many are queued, with
Cancel. Each scrape can take up to a minute: it drives a real headless browser
and scrolls the page. If you hit the rate limit (429), the queue waits,
shows a countdown and retries. If the API key is missing (401), it stops and
offers to set one.

**Playback**: the Play button opens a docked player bar using SoundCloud's own
official embeddable player. Audio comes straight from SoundCloud's
infrastructure; nothing is downloaded or proxied by this app. The play/pause
state comes from the player's own events. So on iOS, which blocks autoplay
in iframes, the bar asks you to press ▶ instead of pretending to play. Only
one track plays at a time, and playback keeps going while you page or filter.
There's no auto-advance and no batch or background playback.

**Download**: a Download link only appears when SoundCloud's own data says the
uploader enabled downloads for that specific track (`downloadable: true`). It
opens the track's own SoundCloud page in a new tab — this app never fetches or
serves the audio file itself, and never offers a download for a track the
artist didn't make downloadable.

It's a single static page ([scraper/app/static/index.html](scraper/app/static/index.html))
with no build step, served by the `frontend` container (nginx) rather than
the API. Editing it needs a `docker compose up --build frontend` to pick up —
the container mounts nothing, so there's no live-reload. The page calls the
API on its own hostname, at `APOLLO_API_PORT` (see
`frontend/40-apollo-config.sh`). So the same deployment works whether you
reach it via localhost, a LAN IP or a Tailscale IP.

If `APOLLO_API_KEY` is set, the front end's 🔑 **API key** button stores the
key in your browser's `localStorage` and attaches it to `/scrape` and
`/api/discover-playlists` requests.

Trigger a scrape via curl instead, if you prefer:

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://soundcloud.com/<artist>/sets/<playlist>"}'
```

Then check the result landed in both places:
- `data/lake/raw/soundcloud/...json` on your machine
- Adminer → `apollo` database → `tracks` table

### Pages that require login

Playlist/set and profile pages (e.g. `soundcloud.com/<user>`) work anonymously.
A personal page like Discover Weekly (`soundcloud.com/discover/sets/weekly::<you>`)
does not — SoundCloud 404s it unless you're logged in as that account, and this
app fails that request with a clear `422` rather than pretending it worked. It
never logs in for you or asks for your password; if you want to try scraping a
page like that, set `APOLLO_SOUNDCLOUD_COOKIES` to your own session cookie (see
`.env.example` for how to get it from your own browser). This path is
untested — no SoundCloud account was available while building it.

### Scheduled ingest

Beyond the on-demand `POST /scrape`, `scraper/app/ingest.py` re-runs the same
fetch → parse → lake → warehouse pipeline against a fixed list of URLs —
useful for keeping a small set of playlists you care about up to date without
opening the UI. It's off by default. Set `APOLLO_INGEST_URLS`
(comma-separated soundcloud.com URLs, e.g. picked from the catalog) to use it:

```bash
docker compose run --rm api python -m app.ingest
```

In Kubernetes this runs on a timer via a `CronJob`
(`infra/terraform-k8s/ingest-cronjob.tf`, `ingest_urls`/`ingest_schedule`
Terraform variables — daily by default). One bad/blocked URL in the list
doesn't stop the others from being ingested. See
[docs/CRAWLER_DESIGN.md](docs/CRAWLER_DESIGN.md) for why this is a fixed-list
re-scrape rather than a crawler that discovers new URLs on its own.

### Full API reference

See [docs/API.md](docs/API.md) for every endpoint, or the live interactive
version at [localhost:8000/docs](http://localhost:8000/docs).

### Logs

Written to stdout (`docker compose logs scraper`) and to `./logs/apollo.log` on
your machine. Once the file exceeds `APOLLO_LOG_MAX_BYTES` (default 5MB) it's
rotated and gzipped (`apollo.log.1.gz`, `.2.gz`, ...); `APOLLO_LOG_BACKUP_COUNT`
(default 10) controls how many are kept before the oldest is deleted.

Every request gets a short id (e.g. `[e7604932]`) that appears on every log
line while it's being handled, even across modules — `grep e7604932
logs/apollo.log` (or `zgrep` on a rotated `.gz` file) pulls the whole story of
one scrape: fetch, parse, lake write, warehouse load, with per-stage timing.

Level is `APOLLO_LOG_LEVEL` in `.env` (default `INFO`). Set it to `DEBUG` for
much more detail — scroll-iteration counts, which DOM selector matched, how
many tracks got hydration-enrichment vs. fell back to profile-owner
attribution, row counts written to the warehouse. Noisy for daily use, useful
when a scrape is behaving oddly.

## Local development (without Docker)

```bash
cd scraper
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install firefox
uvicorn app.main:app --reload
```

## Tests

```bash
cd scraper
pip install -r requirements.txt pytest
pytest
```

## Repository layout

- `scraper/` — the FastAPI + Playwright app (the standalone API, no UI mounted)
  - `app/pipeline.py` — the fetch → parse → lake → warehouse sequence shared by `POST /scrape` and `app/ingest.py`
  - `app/ingest.py` — scheduled re-scrape of a fixed URL list (`APOLLO_INGEST_URLS`), run by `docker compose run` locally or a k8s `CronJob`
  - `app/playlists.py` — the genre -> playlist catalog behind the dropdowns
  - `app/logging_config.py` — logging setup (console + rotating file)
  - `app/static/index.html` — the front end's HTML (scrape, browse, play, download) — served by `frontend/`, not by the API
- `frontend/` — nginx image serving `scraper/app/static/index.html`, decoupled from the API (talks to it over the network — see `docs/HOSTING.md`)
- `warehouse/init.sql` — Postgres schema, auto-applied on first `postgres` container start (also re-runnable by hand as a migration — see the file)
- `docs/API.md` — full API reference
- `docs/CRAWLER_DESIGN.md` — scoping doc for indexing/crawling beyond one profile at a time (not fully built — see the doc for what's done vs. planned)
- `docs/PUBLIC_ACCESS_DESIGN.md` — original design plan for reaching this remotely; see `docs/HOSTING.md` for what's actually built
- `docs/HOSTING.md` — the concrete local-Kubernetes + Tailscale hosting setup and its security checklist
- `infra/terraform-aws/` — unfinished sketch for a future real-AWS deployment (not wired into the local stack — see its README)
- `infra/terraform-k8s/` — Terraform (Kubernetes provider) config for running the decoupled `api`/`frontend` on Docker Desktop's own Kubernetes (or real k3s on a second PC) — `terraform validate`-checked (see its README and `docs/HOSTING.md`)
- `docker-compose.yml` — wires api + frontend + postgres + adminer together

## Known limitations / next steps

- The CSS selectors in `scraping.py` are scraped from SoundCloud's live DOM
  (there's no public scraping API) and will break silently if SoundCloud
  changes its frontend — watch for `track_count: 0` responses. Hydration-state
  reading (see the big comment in `scraping.py`) is the primary path and is
  more robust, but the DOM fallback still matters for profile/stream pages,
  which don't expose track data via hydration at all.
- `genre` coverage varies a lot by page/playlist — SoundCloud doesn't always
  attach a genre to a track, and profile/stream pages don't expose it via the
  DOM at all currently.
- No auth on Adminer, and the API's `X-API-Key` gate (see
  [docs/HOSTING.md](docs/HOSTING.md)) is a deterrent against casual abuse, not
  real authentication — this stack is meant for local/Tailscale use, don't
  expose these ports to the public internet as-is.
- `/scrape` and `/api/discover-playlists` only accept `soundcloud.com` URLs
  (an SSRF guard) and are rate-limited (10/min and 20/min respectively) — see
  [docs/API.md](docs/API.md).
- `APOLLO_SOUNDCLOUD_COOKIES` (for login-gated pages) is unverified — built
  without access to a real SoundCloud login to test against.
