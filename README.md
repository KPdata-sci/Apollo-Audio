# Project Apollo — SoundCloud Scraper

A dockerized SoundCloud playlist/profile scraper with a local data lake and
data warehouse (Postgres), a front end to scrape/browse/play tracks, and no
cloud account required.

## Architecture

```
        POST /scrape
             |
             v
     +---------------+
     |  FastAPI app  |  (scraper/, Playwright + BeautifulSoup)
     +---------------+
        |          |
        v          v
   +-----------+  +----------+
   | ./data/   |  | Postgres |
   | lake/     |->| (wareh.) |
   +-----------+  +----------+
   raw JSON       tracks table
   landing        (queryable)
```

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
| scraper UI | http://localhost:8000        | Front end — scrape + browse tracks |
| scraper API | http://localhost:8000/docs  | FastAPI + Swagger UI            |
| ./data/lake | (local folder)               | Data lake — raw scraped JSON    |
| postgres   | localhost:5432                 | Data warehouse                  |
| adminer    | http://localhost:8081         | Postgres UI (system: PostgreSQL, server: `postgres`) |

### Using the front end

Open [localhost:8000](http://localhost:8000). Three ways to pick what to scrape:
- **Catalog dropdowns** — choose a genre, then a playlist from that genre.
  Empty by default (this project ships generic, with no accounts baked in) —
  add your own in [scraper/app/playlists.py](scraper/app/playlists.py), no
  migration needed. Selecting one fills in the URL box; you still click
  Scrape yourself.
- **Browse a profile's playlists** — paste any profile URL
  (`soundcloud.com/<user>`) and click Browse to list everything on that
  account's `/sets` page, with a Load button per result to send it to the
  scrape box. Read-only — browsing never scrapes anything by itself.
- **Paste a URL directly** — any playlist/set or profile page.

Scraping can take up to a minute (it's driving a real headless browser and
scrolling the page). The tracks table below reads live from the warehouse via
`GET /api/tracks?search=&limit=&offset=`, with a debounced search box (matches
artist or title) and Prev/Next pagination.

**Playback**: each row has a Play button that streams the track via
SoundCloud's own official embeddable player — audio comes straight from
SoundCloud's infrastructure, nothing is downloaded or proxied by this app.
Only one track plays at a time: starting another stops whatever was playing,
there's no batch/background playback.

**Download**: a Download link only appears when SoundCloud's own data says the
uploader enabled downloads for that specific track (`downloadable: true`). It
opens the track's own SoundCloud page in a new tab — this app never fetches or
serves the audio file itself, and never offers a download for a track the
artist didn't make downloadable.

It's a single static page ([scraper/app/static/index.html](scraper/app/static/index.html))
with no build step, served directly by FastAPI — edit and refresh, no rebuild
needed in dev (the container mounts nothing, so for live-reload during UI
work, run `uvicorn app.main:app --reload` locally instead, see below).

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

- `scraper/` — the FastAPI + Playwright app (the scraper itself)
  - `app/playlists.py` — the genre -> playlist catalog behind the dropdowns
  - `app/logging_config.py` — logging setup (console + rotating file)
  - `app/static/index.html` — the front end (scrape, browse, play, download)
- `warehouse/init.sql` — Postgres schema, auto-applied on first `postgres` container start (also re-runnable by hand as a migration — see the file)
- `docs/API.md` — full API reference
- `docs/CRAWLER_DESIGN.md` — scoping doc for indexing/crawling beyond one profile at a time (not fully built — see the doc for what's done vs. planned)
- `docs/PUBLIC_ACCESS_DESIGN.md` — plan for reaching this remotely from a VPS (not yet built)
- `infra/terraform-aws/` — unfinished sketch for a future real-AWS deployment (not wired into the local stack — see its README)
- `docker-compose.yml` — wires scraper + postgres + adminer together

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
- No retry/backoff or rate-limiting between scrape requests yet.
- No auth on the API or on Adminer — this stack is for local use only, don't
  expose these ports publicly as-is.
- `APOLLO_SOUNDCLOUD_COOKIES` (for login-gated pages) is unverified — built
  without access to a real SoundCloud login to test against.
