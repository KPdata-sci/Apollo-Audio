CREATE TABLE IF NOT EXISTS tracks (
    id               SERIAL PRIMARY KEY,
    artist           VARCHAR(255) NOT NULL,
    title            VARCHAR(255) NOT NULL,
    genre            VARCHAR(255),
    url              VARCHAR(1024),
    downloadable     BOOLEAN NOT NULL DEFAULT FALSE,
    source_url       VARCHAR(1024) NOT NULL,
    lake_object_key  VARCHAR(1024) NOT NULL,
    scraped_at       TIMESTAMPTZ NOT NULL,
    -- `url` (the track's permalink) is the track's real stable identity — artist
    -- attribution can legitimately change between scrapes (e.g. a selector fix),
    -- so it must not be part of the conflict key or re-scrapes create duplicates
    -- instead of updating the existing row.
    UNIQUE (url)
);

CREATE INDEX IF NOT EXISTS idx_tracks_scraped_at ON tracks (scraped_at);

-- This file only runs automatically against a brand-new, empty Postgres data
-- volume (docker-entrypoint-initdb.d semantics). The ADD COLUMN below is a
-- no-op there (the column already exists from CREATE TABLE above) but keeps
-- this file re-runnable by hand as a migration against an existing volume
-- created before the `downloadable` column existed.
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS downloadable BOOLEAN NOT NULL DEFAULT FALSE;

-- SoundCloud's own popularity counters, refreshed from hydration data on every
-- (re)scrape (see app/scraping.py::_track_from_hydration) — nullable because
-- DOM-only fallback parsing (profile/stream pages hydration doesn't cover)
-- has no signal for these, same as `downloadable` before enrichment applies.
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS playback_count BIGINT;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS likes_count BIGINT;

-- A track's own popularity counters are fine to overwrite on every rescrape
-- (they're just SoundCloud's live numbers) — but a favorite is a decision a
-- person made in this app, so it lives in its own table rather than a column
-- on `tracks`, where the UPSERT's `ON CONFLICT DO UPDATE` would otherwise
-- need a special case to avoid wiping it out every time the track resurfaces
-- in a rescrape. No user table (this app has no accounts) — one shared list,
-- matching the rest of the app's no-auth, single-tenant design.
CREATE TABLE IF NOT EXISTS favorites (
    track_id    INTEGER PRIMARY KEY REFERENCES tracks (id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
