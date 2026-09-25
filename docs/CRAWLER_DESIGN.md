# Crawler design (scoping — not yet built beyond Phase 1)

This is a plan, not a shipped feature. Phase 1 (single-profile playlist
discovery) is built and live today as "Browse a profile's playlists" — see
`discover_playlists()` in `scraper/app/scraping.py` and `POST
/api/discover-playlists`. Everything below Phase 1 is design only.

## What's actually on offer on soundcloud.com (researched today, live)

Before designing a crawler it's worth knowing what pages actually exist to
crawl and whether they're reachable anonymously. Tested directly against the
live site while building this:

| Surface | URL pattern | Status | What it gives you |
|---|---|---|---|
| A profile's playlists | `/​<user>/sets` | 200, works anonymously | Full list of that user's own playlists — **implemented** (Phase 1) |
| A profile's tracks | `/<user>` | 200, works anonymously | Already scrapeable via the existing `/scrape` endpoint |
| Genre tag pages | `/tags/<genre>` | 200, works anonymously | A list of individual **tracks** (not playlists) across many different uploaders — e.g. `/tags/drum-and-bass` returned ~55 distinct track links in one page load. A good seed source for discovering *artists*, not playlists. |
| Search (sets) | `/search/sets?q=<term>` | 200, works anonymously | Page loads, but unlike playlist pages it has **no `__sc_hydration` playlist data at all** — content is fetched client-side after load. DOM-scroll extraction (like the tag pages) would need to be built and verified; not yet tested. |
| Discover | `/discover` | 200 anonymously | Loads, but this is almost certainly generic/editorial content when not logged in, not personalized. Not yet tested for what it actually contains. |
| Charts | `/charts`, `/charts/top` | **404** in this test | SoundCloud's chart pages exist conceptually (page `<title>` still references "top played music charts") but the current URL/param scheme wasn't found in this session. Needs more research before building against it — don't assume the old `/charts/top?genre=...&country=...` format still works. |
| A personal feed (e.g. Discover Weekly) | `/discover/sets/weekly::<user>` | 404 without login | Already handled — returns a clear 422 from this app's `/scrape`, see `_LOGIN_REQUIRED_MARKER` in `main.py`. |

Takeaway: the two solid, verified discovery sources right now are **a
profile's own playlist list** (done) and **genre tag pages for finding
tracks/artists** (not yet built). Search and Discover are plausible but need
their own extraction logic verified before relying on them. Charts is a dead
end until someone finds the current URL scheme.

## What "indexing" means here

Right now, scraping is one-shot: you give a URL, it's scraped immediately.
A crawler needs a middle step — a table of URLs that have been *discovered*
but not necessarily *scraped* — so discovery and scraping are decoupled and
the user can review before committing to a scrape. This matches the "don't
mass-download, give the user control" principle already built into playback
and downloads; the crawler should inherit it rather than becoming the one part
of the app that acts autonomously.

### Proposed schema

```sql
CREATE TABLE crawl_pages (
    id              SERIAL PRIMARY KEY,
    url             VARCHAR(1024) NOT NULL UNIQUE,
    page_type       VARCHAR(32) NOT NULL,   -- 'profile' | 'playlist' | 'tag'
    status          VARCHAR(32) NOT NULL DEFAULT 'discovered',
                     -- 'discovered' | 'queued' | 'scraped' | 'failed' | 'skipped'
    depth           INT NOT NULL DEFAULT 0, -- hops from the seed URL
    parent_url      VARCHAR(1024),          -- what led here, for provenance
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    scraped_at      TIMESTAMPTZ
);
```

This is deliberately just another Postgres table, not a separate queue
service (no Redis/Celery/RQ) — this is a single-user local tool; a `SELECT
... WHERE status = 'discovered' ORDER BY discovered_at LIMIT N` is the entire
"frontier."

## Proposed phases

**Phase 1 — done.** Point at one profile, list its playlists, user picks one
to scrape. No index table needed — it's synchronous and stateless.

**Phase 2 — indexed, multi-source discovery (not built).**
- Add the `crawl_pages` table above.
- Generalize `discover_playlists`-style extraction to also handle:
  - Genre tag pages → discovered *profile* URLs (from the track links found there)
  - A profile's tracks page → discovered nothing further by default (tracks are leaf nodes, not links to more pages) unless reposts are followed (see risk below)
- Every discovery run inserts new rows into `crawl_pages` with
  `status='discovered'` (`ON CONFLICT (url) DO NOTHING` — first discovery wins,
  keeps the original `depth`/`parent_url` for provenance).
- New read-only endpoint, `GET /api/crawl/pages`, and a browser panel in the
  front end (same pattern as the tracks table) so discovered-but-unscraped
  pages are visible and reviewable — mirroring how "Browse a profile's
  playlists" already lets you see before you scrape.

**Phase 3 — bounded crawl loop (not built).**
- A `POST /api/crawl/run` that: pulls up to `max_pages` rows with
  `status='discovered'`, runs discovery (not scraping) on each, marks them
  `status='queued'`, with a fixed delay between requests (reuse
  `settings.scroll_pause_ms`-style config, add `crawl_delay_ms`).
- A **separate, explicit** action to actually scrape queued pages — discovery
  and scraping stay decoupled all the way through, so nothing gets scraped
  without the user having seen it in the index first.
- Hard caps, not suggestions: `max_depth` (recommend 2 — seed, then one hop
  out) and `max_pages_per_run` (recommend a small default like 20), both
  because unbounded crawling of a "related content" graph is genuinely
  unbounded, and because hammering SoundCloud with requests is a real ToS/
  courtesy concern this project has taken seriously from the start (see the
  login-wall handling and the deliberate choice not to build a downloader that
  ignores an artist's own download setting). A crawler is the one component
  here with the most potential to turn "personal scraping tool" into
  something that looks like abuse if left unbounded — the caps are load-
  bearing, not just nice-to-haves.
- Runs as a plain `asyncio` background task (FastAPI `BackgroundTasks` or a
  simple in-process loop) — no job queue infrastructure needed at this scale.

## Explicitly out of scope for now

- **Recursive "related tracks/playlists" following.** SoundCloud surfaces
  "related" content on track and playlist pages; this is a plausible richer
  discovery source but wasn't explored this session, and it's the one edge
  most likely to produce an effectively unbounded graph. If added later, it
  needs its own depth cap independent of the others.
- **Reposts tabs** (`/<user>/reposts`) as a discovery source — plausible,
  points at other artists' content, not tested.
- **Charts** — blocked on finding the current URL scheme.
- **Discovery/crawling running on a schedule unattended** — every phase above
  still assumes a person is choosing when to run *discovery* (finding new
  URLs to consider) and when to scrape, for the ToS/courtesy reasons in
  Phase 3 above. This is distinct from what's actually built in
  `scraper/app/ingest.py`: a scheduled **re-scrape of a small, fixed, hand-
  chosen list of URLs** (`APOLLO_INGEST_URLS`), not a crawler that discovers
  new URLs on its own — there's no recursion, no growing frontier, and the
  target set only changes when a person edits the config. It's a much
  narrower courtesy footprint than the crawler this doc scopes, but it's
  still unattended scheduled traffic to SoundCloud, so keep the URL list
  short and the schedule infrequent (see `ingest_schedule` in
  `infra/terraform-k8s/variables.tf`, daily by default) rather than treating
  it as a green light for the crawler design above.
