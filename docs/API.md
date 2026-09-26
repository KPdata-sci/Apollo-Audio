# API Reference

Base URL: `http://localhost:8000` for local dev. This is a standalone API,
decoupled from the front end (`frontend/`, a separate nginx container/Service)
— see `docs/HOSTING.md` for the split and why.

Interactive docs (try-it-out, generated from the same code): `GET /docs` (Swagger UI) or `GET /redoc`.

**Caching**: successful `GET /api/*` JSON responses carry a weak `ETag`. `GET /api/playlists` is `Cache-Control: public, max-age=3600`, because the catalog only changes on redeploy. Everything else is `no-cache`: the browser revalidates on every load and gets a body-less `304` when nothing changed, so the data is never stale after a scrape. Responses over 1KB are gzipped when the client accepts it.

**Auth**: `POST /scrape`, `POST /api/discover-playlists`, and the favorite
endpoints below require an `X-API-Key` header matching `APOLLO_API_KEY` *when
that setting is non-empty* — it's empty (no auth) by default for local dev.
`GET /api/tracks`, `GET /api/stats`, and `GET /api/playlists` are never
gated. See `docs/HOSTING.md` for what this does and doesn't protect against.

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
      "downloadable": false,
      "playback_count": 14555,
      "likes_count": 560,
      "artwork_url": "https://i1.sndcdn.com/artworks-<id>-t500x500.jpg"
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

`playback_count`/`likes_count` are SoundCloud's own counters, read from the same hydration state as `genre`/`downloadable` — so they share the same limitation: a playlist/set page carries them for every track, but a profile/stream page's hydration has no per-track data at all, so both come back `null` there (same as `genre` already does).

`artwork_url` is always a SoundCloud CDN url (or `null`, only when nothing at all was available), never a file this API hosts — it's the track's own artwork when SoundCloud has one, falling back to the uploader's avatar when it doesn't (matching SoundCloud's own UI, and how a profile/stream page track always gets *some* image). Same policy boundary as playback and downloads: this API hotlinks, it never downloads or rehosts SoundCloud's media itself.

---

## `GET /api/tracks`

Paginated, searchable read of everything currently in the warehouse.

**Query params**
| Param | Default | Notes |
|---|---|---|
| `search` | `""` | Case-insensitive literal substring match against artist or title (`%` and `_` match themselves, not as wildcards). |
| `genre` | `""` | Case- and surrounding-whitespace-insensitive exact match. Use a `genre` value from `GET /api/stats`. |
| `source_url` | `""` | Exact match on the playlist/profile URL a track was scraped from. |
| `sort` | `recent` | `recent` (newest scrape first), `artist`, `title`, or `popular` (highest `playback_count` first; tracks with none known sort last, not excluded). Anything else → `422`. |
| `favorited_only` | `false` | Only tracks favorited via `POST /api/tracks/{id}/favorite`. |
| `limit` | `50` | Clamped to 1-200. |
| `offset` | `0` | |

Filters combine, and `total` is the filtered count. A NUL character in `search`, `genre` or `source_url` gives a `422`.

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
      "playback_count": 14555,
      "likes_count": 560,
      "artwork_url": "https://i1.sndcdn.com/artworks-<id>-t500x500.jpg",
      "favorited": false,
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

## `POST /api/tracks/{id}/favorite` · `DELETE /api/tracks/{id}/favorite`

Adds or removes a track from the shared favorites list. There are no user
accounts in this app (see `docs/HOSTING.md`/`CLAUDE.md`), so it's one shared
list rather than per-person — consistent with the rest of the app's
single-tenant design. Both are idempotent: favoriting an already-favorited
track, or un-favoriting one that was never favorited, just returns the same
result rather than erroring.

**Response `200`**
```json
{"id": 1, "favorited": true}
```

**Errors**
| Status | When |
|---|---|
| `401` | `APOLLO_API_KEY` is set and the request's `X-API-Key` header is missing or wrong. |
| `404` | No track with this id exists. |

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

## `GET /api/stats`

Headline numbers and filter facets for the library view. Read-only, no auth.

**Response `200`**
```json
{
  "total_tracks": 241,
  "total_sources": 4,
  "total_favorites": 3,
  "last_scraped_at": "2026-09-25T17:22:00.445729Z",
  "genres": [{"genre": "Drum & Bass", "count": 32}],
  "sources": [{"source_url": "https://soundcloud.com/<user>/sets/<slug>", "track_count": 58, "last_scraped_at": "2026-09-25T17:22:00Z"}]
}
```
- `genres` groups spellings together regardless of case and surrounding whitespace ("Hip-hop/Rap" and "Hip-Hop/Rap " count as one), shows the most common spelling, and leaves out blank genres and `#`-hashtag spam. It's sorted by count and capped at 40. Every `genre` returned works as a `/api/tracks?genre=` filter and returns exactly `count` tracks.
- `sources` is sorted by most recent scrape, and capped at 100.
- `last_scraped_at` is `null` when the warehouse is empty.

---

## `GET /api/playlists`

Returns the curated `{genre: [{name, url, note}]}` catalog behind the front end's Discover view. It holds about 19 genres of public playlists, mostly from SoundCloud's own editorial accounts, and each one was checked with the real scraper when added (2026-09-25). `note` flags entries that behave differently, such as profiles instead of sets, or weekly charts that rotate. Edit `scraper/app/playlists.py` to change it. No migration or restart is needed: it's read fresh on each request.

**Response `200`** (abridged)
```json
{
  "Drum & Bass": [
    {"name": "Fresh Drum & Bass: Bassbin", "url": "https://soundcloud.com/soundcloud-uk/sets/bassbin-fresh-drum-and-bass", "note": null}
  ]
}
```

---

## Playback, downloads, and artwork

This API never streams, stores, or proxies SoundCloud's own media itself:

- **Playback** is done client-side via SoundCloud's own official embeddable player (`w.soundcloud.com/player`), pointed at the track's `url`. Audio is streamed directly from SoundCloud's own infrastructure, one track at a time (starting a new one stops whatever was playing) — there's no batch/background playback.
- **Downloads** are a link to the track's own SoundCloud page, shown only when `downloadable` is `true`. Whether the actual download button appears there, and whether it works, is entirely SoundCloud's and the uploader's own choice — this project does not fetch, cache, or redistribute audio files under any circumstance.
- **Artwork** (`artwork_url`) is likewise never downloaded or rehosted — the front end hotlinks it directly from SoundCloud's own CDN (`i1.sndcdn.com`). This API only ever stores the *url*, not image bytes.

---

## Logging

All requests and scrape lifecycle events are logged to stdout (`docker compose logs scraper`) and to `./logs/apollo.log` on the host, rotated and gzipped once the file exceeds `APOLLO_LOG_MAX_BYTES` (default 5MB; `APOLLO_LOG_BACKUP_COUNT`, default 10, controls how many rotated `.gz` files are kept).

Every request is tagged with a short id (shown as `[xxxxxxxx]` in each log line) that's shared by every log line emitted while handling it, across modules — `grep <id> logs/apollo.log` pulls the full fetch/parse/lake/warehouse story of one scrape. `APOLLO_LOG_LEVEL=DEBUG` adds per-stage timing and internal detail (scroll iterations, DOM selector matches, hydration enrichment counts).
