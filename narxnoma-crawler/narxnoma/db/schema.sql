-- Idempotent. Safe to run on every start.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS store (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         text UNIQUE NOT NULL,
    name         text NOT NULL,
    website_url  text NOT NULL,
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Append-only observation log. Price history falls out of this for free.
CREATE TABLE IF NOT EXISTS raw_offer (
    id           bigserial PRIMARY KEY,
    store_id     uuid NOT NULL REFERENCES store(id),
    source_key   text NOT NULL,
    name_raw     text NOT NULL,
    price        bigint NOT NULL CHECK (price BETWEEN 100000 AND 100000000),
    url          text NOT NULL,
    availability text NOT NULL DEFAULT 'UNKNOWN',
    image_url    text,
    payload      jsonb,
    observed_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_offer_store_key_time
    ON raw_offer (store_id, source_key, observed_at DESC);

-- Current state, one row per retailer listing. variant_id is filled in Plan 3.
CREATE TABLE IF NOT EXISTS offer (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id     uuid NOT NULL REFERENCES store(id),
    source_key   text NOT NULL,
    variant_id   uuid,
    name_raw     text NOT NULL,
    price        bigint NOT NULL CHECK (price BETWEEN 100000 AND 100000000),
    url          text NOT NULL,
    availability text NOT NULL DEFAULT 'UNKNOWN',
    image_url    text,
    first_seen   timestamptz NOT NULL DEFAULT now(),
    last_seen    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (store_id, source_key)
);
CREATE INDEX IF NOT EXISTS offer_last_seen ON offer (last_seen DESC);
CREATE INDEX IF NOT EXISTS offer_variant ON offer (variant_id);

-- One row per source per cycle. Makes a silently-dead source visible.
CREATE TABLE IF NOT EXISTS harvest_run (
    id            bigserial PRIMARY KEY,
    store_id      uuid NOT NULL REFERENCES store(id),
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    ok            boolean,
    listings_seen integer NOT NULL DEFAULT 0,
    listings_kept integer NOT NULL DEFAULT 0,
    error         text
);

INSERT INTO store (slug, name, website_url) VALUES
    ('uzum',      'Uzum',      'https://uzum.uz'),
    ('alifshop',  'Alif Shop', 'https://alifshop.uz'),
    ('beemarket', 'BeeMarket', 'https://market.beeline.uz'),
    ('idea',      'Idea',      'https://idea.uz'),
    ('mediapark', 'Mediapark', 'https://mediapark.uz'),
    ('olcha',     'Olcha',     'https://olcha.uz'),
    ('texnomart', 'Texnomart', 'https://texnomart.uz')
ON CONFLICT (slug) DO NOTHING;
