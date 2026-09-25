# API Reference

Base URL: `http://localhost:8000` for local dev. This is a standalone API,
decoupled from the front end (`frontend/`, a separate nginx container/Service)
— see `docs/HOSTING.md` for the split and why.

Interactive docs (try-it-out, generated from the same code): `GET /docs` (Swagger UI) or `GET /redoc`.

**Auth**: `POST /scrape` and `POST /api/discover-playlists` require an
`X-API-Key` header matching `APOLLO_API_KEY` *when that setting is
non-empty* — it's empty (no auth) by default for local dev. `GET /api/tracks`
and `GET /api/playlists` are never gated. See `docs/HOSTING.md` for what this
does and doesn't protect against.

---

## `GET /health`

Liveness check. Always returns `{"status": "ok"}` if the process is up — doesn't check Postgres or lake connectivity.

**Response `200`**
```json
{"status": "ok"}
```

---

## `POST /scrape`

Scrapes a SoundCloud playlist, set, or profile page, lands the raw result in the data lake, then upserts it into the warehouse.

Takes ~10-60 seconds — it drives a real headless browser and scrolls the page to trigger SoundCloud's own lazy-loading before reading the result.

**Request body**
```json
{"url": "https://soundcloud.com/<artist>/sets/<playlist>"}
```

**Response `200`**
```json
{
  "source_url": "https://soundcloud.com/<artist>/sets/<playlist>",
  "scraped_at": "2026-09-25T12:39:15.984000Z",
  "track_count": 59,
  "lake_object_key": "raw/soundcloud/2026/09/25/123915_<artist>_sets_<playlist>.json",
  "tracks": [
    {
      "title": "...",
      "artist": "...",
      "genre": "Drum & Bass",
      "url": "https://soundcloud.com/...",
      "downloadable": false
    }
  ]
}
```

**Errors**
| Status | When |
|---|---|
| `401` | `APOLLO_API_KEY` is set and the request's `X-API-Key` header is missing or wrong. |
| `422` | The URL isn't a `soundcloud.com` URL, or SoundCloud's own page says this requires being logged in as its owner (e.g. a personal Discover Weekly — see `APOLLO_SOUNDCLOUD_COOKIES` in `.env.example`). |
| `429` | Rate limit exceeded (10 requests/minute, keyed by `X-API-Key` when set, otherwise by IP). |
| `502` | The headless browser failed to load the page at all after retries (timeout, network error, SoundCloud unreachable), or the result failed to write to the data lake. |

`downloadable` is only ever `true` when SoundCloud's own data says the uploader enabled downloads for that specific track — it is never inferred. The front end uses it to decide whether to show a download link at all; that link always points at the track's own SoundCloud page (this API never serves or proxies audio files).

---

## `GET /api/tracks`

Paginated, searchable read of everything currently in the warehouse.

**Query params**
| Param | Default | Notes |
|---|---|---|
| `search` | `""` | Case-insensitive substring match against artist or title. |
| `limit` | `50` | Clamped to 1-200. |
| `offset` | `0` | |

**Response `200`**
```json
{
  "items": [
    {
      "id": 1,
      "artist": "...",
      "title": "...",
      "genre": "...",
      "url": "https://soundcloud.com/...",
      "downloadable": false,
      "source_url": "https://soundcloud.com/<artist>/sets/<playlist>",
      "scraped_at": "2026-09-25T12:02:19.202248Z"
    }
  ],
  "total": 533,
  "limit": 50,
  "offset": 0
}
```

---

## `POST /api/discover-playlists`

Browses a profile's `/sets` page and lists its playlists — a read-only step, separate from scraping. Doesn't touch the lake or warehouse.

**Request body**
```json
{"profile_url": "https://soundcloud.com/<user>"}
```

**Response `200`**
```json
{
  "profile_url": "https://soundcloud.com/<user>",
  "playlists": [
    {"name": "...", "url": "https://soundcloud.com/<user>/sets/<slug>", "note": null}
  ]
}
```

**Errors**
| Status | When |
|---|---|
| `401` | `APOLLO_API_KEY` is set and the request's `X-API-Key` header is missing or wrong. |
| `422` | The URL isn't a `soundcloud.com` URL. |
| `429` | Rate limit exceeded (20 requests/minute, keyed by `X-API-Key` when set, otherwise by IP). |
| `502` | The headless browser failed to load the profile page after retries. |

---

## `GET /api/playlists`

Returns the curated `{genre: [{name, url, note}]}` catalog that powers the front end's genre/playlist dropdowns. **Empty by default** — this project ships generic, with no accounts baked in. Edit `scraper/app/playlists.py` to add your own — no migration or restart needed, it's read fresh on each request.

**Response `200`** (after adding entries — see `scraper/app/playlists.py` for the format)
```json
{
  "Some Genre": [
    {"name": "A playlist I like", "url": "https://soundcloud.com/<user>/sets/<slug>", "note": null}
  ]
}
```

---

## Playback and downloads

This API never streams, stores, or proxies audio itself:

- **Playback** is done client-side via SoundCloud's own official embeddable player (`w.soundcloud.com/player`), pointed at the track's `url`. Audio is streamed directly from SoundCloud's own infrastructure, one track at a time (starting a new one stops whatever was playing) — there's no batch/background playback.
- **Downloads** are a link to the track's own SoundCloud page, shown only when `downloadable` is `true`. Whether the actual download button appears there, and whether it works, is entirely SoundCloud's and the uploader's own choice — this project does not fetch, cache, or redistribute audio files under any circumstance.

---

## Logging

All requests and scrape lifecycle events are logged to stdout (`docker compose logs scraper`) and to `./logs/apollo.log` on the host, rotated and gzipped once the file exceeds `APOLLO_LOG_MAX_BYTES` (default 5MB; `APOLLO_LOG_BACKUP_COUNT`, default 10, controls how many rotated `.gz` files are kept).

Every request is tagged with a short id (shown as `[xxxxxxxx]` in each log line) that's shared by every log line emitted while handling it, across modules — `grep <id> logs/apollo.log` pulls the full fetch/parse/lake/warehouse story of one scrape. `APOLLO_LOG_LEVEL=DEBUG` adds per-stage timing and internal detail (scroll iterations, DOM selector matches, hydration enrichment counts).
