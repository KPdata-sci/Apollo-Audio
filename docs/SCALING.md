# Scaling notes: popularity & favorites

Options for the day this stops being "a few hundred tracks on one Postgres
instance." Nothing here is built — this is a menu to pick from once a
specific bottleneck actually shows up, not work to do preemptively.

## Popularity data goes stale between scrapes

`playback_count`/`likes_count` are only ever as fresh as the last full
scrape (see `docs/CRAWLER_DESIGN.md` for why re-scraping isn't automatic or
frequent). A full `/scrape` re-drives a real headless browser and scroll —
expensive, and overkill just to refresh two numbers.

- **Cheaper refresh path**: SoundCloud exposes track metadata (including
  `playback_count`/`likes_count`) through lighter-weight requests than a full
  page load — e.g. its `oembed`/`resolve` endpoints. A second, cheap ingest
  mode that just re-fetches known track urls and updates those two columns
  (no `Playwright`, no scrolling) could run far more often than the existing
  `CronJob` (hourly instead of daily) without the cost of a full rescrape.
- **Materialized ranking**: once the `tracks` table is large enough that
  `ORDER BY coalesce(playback_count, 0) DESC` over the whole table shows up
  in query latency, a small `popular_tracks` materialized view (refreshed on
  a schedule via `REFRESH MATERIALIZED VIEW CONCURRENTLY`) turns that into a
  pre-sorted read instead of a live sort every request.

## Favorites are single-tenant by design, for now

`favorites` has no `user_id` — one shared list, matching the rest of this
app's no-accounts design (see `CLAUDE.md`). If that ever needs to change
(e.g. separate "mine" vs. "household" favorites), the schema extends rather
than migrates: add a `user_id` (a real account id, or just a
cookie-stored anonymous device id — no need to build full auth for this
specifically) into `favorites`' primary key alongside `track_id`. Nothing
elsewhere in the app assumes a single row per track.

## Postgres access patterns

- **Connection-per-call**: `warehouse.py` opens a fresh `psycopg.connect()`
  for every call (`list_tracks`, `get_stats`, `add_favorite`, ...). Fine at
  today's request volume; wasteful once concurrent traffic grows enough that
  connection setup (TCP + auth) becomes a meaningful fraction of request
  time. `psycopg_pool` (a small, drop-in connection pool) is the natural next
  step — the calling code in `main.py` wouldn't need to change.
- **Indexes**: `favorites` is joined on its own primary key
  (`favorites.track_id`), so that join is already indexed for free. The
  genre facet (`_GENRE_FACET_SQL`) groups on `lower(btrim(genre, ...))` with
  no matching index — currently a fast sequential scan at this table size,
  but worth a functional index (`CREATE INDEX ... ON tracks
  (lower(btrim(genre, E' \t\r\n')))`) if `/api/stats` latency ever becomes
  visible.
- **Read scaling**: if a "Popular" or "Favorites" view gets hit hard enough
  to matter (e.g. embedded somewhere with real traffic), a Postgres read
  replica behind `list_tracks`/`get_stats` is the standard next step — no
  code changes beyond pointing read-only queries at a second DSN.

## Artwork is hotlinked, not mirrored

`artwork_url` is always SoundCloud's own CDN url (see `CLAUDE.md`'s
playback/download/artwork policy note) — the front end's `<img>` tags fetch
it directly from `i1.sndcdn.com`, so this app carries none of that bandwidth
and needs no image storage. The trade-off: a url captured at scrape time is
only as durable as SoundCloud's own CDN keeps it working (an already-broken
one just shows the colored-initials fallback the front end always renders
underneath — see `trackHtml()` in `index.html`). If that ever becomes a
real problem (a noticeable fraction of images going dead, or wanting
artwork available even if a track's SoundCloud page later disappears), the
next step is a proper caching proxy — fetch once, store in the data lake or
a CDN-backed bucket, serve from there — not something to build ahead of
seeing it actually matter.

## Caching

`GET /api/tracks` already revalidates via ETag on every load (see
`docs/API.md`), which is right for a page a person is actively editing
filters on, but "most popular" and "favorites" both change far less often in
practice than "most recent." A short `public, max-age=60`-style policy
(same mechanism `/api/playlists` already uses, just a much shorter window)
would let repeated hits to `sort=popular` skip re-querying the database
entirely for a minute at a time, at the cost of up-to-a-minute staleness —
a reasonable trade for a "popular this week" kind of view.
