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

-- The track's own artwork, or the uploader's avatar as a fallback when a
-- track has none of its own (see app/scraping.py::_track_from_hydration) —
-- always SoundCloud's own CDN url, hotlinked rather than mirrored (this app
-- never downloads/rehosts SoundCloud's media, same policy as audio — see
-- CLAUDE.md). Refreshed on every rescrape like the other SoundCloud-owned
-- counters above.
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS artwork_url VARCHAR(1024);

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

-- User accounts. No public signup (see CLAUDE.md) — rows are created by hand
-- via `python -m app.create_user`, never through an HTTP endpoint.
-- password_hash is an Argon2id-encoded string (app/auth.py) — the salt lives
-- inside that string itself (standard PHC format), not a separate column.
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (username)
);

-- Favorites started as one shared, unauthenticated list (track_id alone as
-- the primary key) and become per-user here. Restructuring an existing
-- table's primary key is only safe while it's empty, so this checks rather
-- than assumes: it no-ops if user_id already exists (already migrated), and
-- fails loudly instead of silently corrupting data if the table somehow has
-- rows with no owner to assign them to.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'favorites' AND column_name = 'user_id'
    ) THEN
        IF EXISTS (SELECT 1 FROM favorites LIMIT 1) THEN
            RAISE EXCEPTION
                'favorites has existing rows with no user_id to assign them to — this table was expected to be empty before the per-user migration; resolve manually before re-running.';
        END IF;
        ALTER TABLE favorites ADD COLUMN user_id INTEGER REFERENCES users (id) ON DELETE CASCADE;
        ALTER TABLE favorites ALTER COLUMN user_id SET NOT NULL;
        ALTER TABLE favorites DROP CONSTRAINT favorites_pkey;
        ALTER TABLE favorites ADD PRIMARY KEY (user_id, track_id);
    END IF;
END $$;
