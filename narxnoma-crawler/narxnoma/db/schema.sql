-- Idempotent. Executed on every application start.
--
-- HOW TO CHANGE THIS FILE. Never edit an existing CREATE TABLE to add or alter a
-- column: CREATE TABLE IF NOT EXISTS is a no-op on a database that already has the
-- table, so the change would apply on a fresh database and silently not apply in
-- production. Instead append an explicit migration at the bottom of the file --
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS ... -- and bump the schema_version row.

CREATE TABLE IF NOT EXISTS schema_version (
    version     integer PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_version (version) VALUES (1) ON CONFLICT (version) DO NOTHING;

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
    availability text NOT NULL DEFAULT 'UNKNOWN'
        CHECK (availability IN ('IN_STOCK', 'OUT_OF_STOCK', 'UNKNOWN')),
    image_url    text,
        payload      jsonb,
        observed_at  timestamptz NOT NULL DEFAULT now()
    );
    -- Plan 5: which category sweep produced this observation (defaults smartphones).
    ALTER TABLE raw_offer ADD COLUMN IF NOT EXISTS category text NOT NULL DEFAULT 'smartphones';
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
    availability text NOT NULL DEFAULT 'UNKNOWN'
        CHECK (availability IN ('IN_STOCK', 'OUT_OF_STOCK', 'UNKNOWN')),
    image_url    text,
        first_seen   timestamptz NOT NULL DEFAULT now(),
        last_seen    timestamptz NOT NULL DEFAULT now(),
        UNIQUE (store_id, source_key)
    );
    -- Plan 5: which category sweep produced this offer (defaults smartphones).
    ALTER TABLE offer ADD COLUMN IF NOT EXISTS category text NOT NULL DEFAULT 'smartphones';
    CREATE INDEX IF NOT EXISTS offer_last_seen ON offer (last_seen DESC);
    CREATE INDEX IF NOT EXISTS offer_variant ON offer (variant_id) WHERE variant_id IS NOT NULL;

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
CREATE INDEX IF NOT EXISTS harvest_run_store_started
    ON harvest_run (store_id, started_at DESC);

INSERT INTO store (slug, name, website_url) VALUES
    ('uzum',      'Uzum',      'https://uzum.uz'),
    ('alifshop',  'Alif Shop', 'https://alifshop.uz'),
    ('beemarket', 'BeeMarket', 'https://market.beeline.uz'),
    ('idea',      'Idea',      'https://idea.uz'),
    ('mediapark', 'Mediapark', 'https://mediapark.uz'),
    ('olcha',     'Olcha',     'https://olcha.uz'),
    ('texnomart', 'Texnomart', 'https://texnomart.uz')
ON CONFLICT (slug) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Migration 2: canonical products. Appended, never edited into the tables
-- above -- see the header comment.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS variant (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand         text NOT NULL,
    model_tokens  text[] NOT NULL,
    ram_gb        integer,                 -- NULL is legitimate: Apple omits RAM
        storage_gb    integer NOT NULL,        -- NOT NULL for phones (see Plan 5 note)
        color         text NOT NULL,           -- hard identity field for PHONES
        sim_kind      text NOT NULL CHECK (sim_kind IN ('dual', 'esim_only')),
        display_name  text NOT NULL,           -- generated from the key, never copied
        slug          text UNIQUE NOT NULL,
        category      text NOT NULL DEFAULT 'smartphones',
        created_at    timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS variant_identity
        ON variant (brand, ram_gb, storage_gb, sim_kind);
    CREATE INDEX IF NOT EXISTS variant_siblings
        ON variant (brand, storage_gb, ram_gb, sim_kind);   -- colour-sibling lookup

    -- Plan 5 (categories, 2026-08-10): non-phone categories (televisions,
    -- laptops, ACs, fridges, washers, ovens) carry no colour/SIM identity, so
    -- both hard identity fields become nullable. Idempotent by construction:
    -- DROP NOT NULL on an already-nullable column is a no-op, and the sim_kind
    -- CHECK passes for NULL (UNKNOWN). Existing phone rows are untouched.
    ALTER TABLE variant ALTER COLUMN color DROP NOT NULL;
    ALTER TABLE variant ALTER COLUMN sim_kind DROP NOT NULL;
    -- storage_gb is also relaxed: a TV or fridge has no memory figure, and
    -- requiring one would make most appliances unkeyable.
    ALTER TABLE variant ALTER COLUMN storage_gb DROP NOT NULL;

-- min_price is NULLABLE on purpose. Only IN_STOCK offers may set a headline
-- price, and a variant can legitimately have offers where every one of them is
-- out of stock. NOT NULL would force us either to publish an out-of-stock price
-- as if it were buyable, or to delete the row and lose the variant's history.
CREATE TABLE IF NOT EXISTS variant_price (
    variant_id            uuid PRIMARY KEY REFERENCES variant(id) ON DELETE CASCADE,
    min_price             bigint,
    min_store_id          uuid REFERENCES store(id),
    min_offer_id          uuid REFERENCES offer(id),
    median_price          bigint,
    max_price             bigint,
    offer_count           integer NOT NULL DEFAULT 0,
    in_stock_offer_count  integer NOT NULL DEFAULT 0,
    store_count           integer NOT NULL DEFAULT 0,
    computed_at           timestamptz NOT NULL DEFAULT now(),
    CHECK ((min_price IS NULL) = (in_stock_offer_count = 0))
);

CREATE TABLE IF NOT EXISTS unresolved_offer (
    offer_id       uuid PRIMARY KEY REFERENCES offer(id) ON DELETE CASCADE,
    reason         text NOT NULL CHECK (reason <> ''),
    candidate_ids  uuid[] NOT NULL DEFAULT '{}',
    recorded_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS unresolved_reason ON unresolved_offer (reason);

DO $$ BEGIN
    ALTER TABLE offer ADD CONSTRAINT offer_variant_fk
        FOREIGN KEY (variant_id) REFERENCES variant(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

INSERT INTO schema_version (version) VALUES (2) ON CONFLICT (version) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Migration 3: asaxiy.uz, the eighth source.
--
-- Appended rather than added to the migration-1 seed list above, per the
-- header: that INSERT already ran in production, and `ON CONFLICT (slug) DO
-- NOTHING` makes re-running it a no-op for the seven rows that exist -- but
-- the row for an EIGHTH store would only ever be inserted on a database
-- fresh enough to be running migration 1 for the first time. On production
-- it would silently never appear, harvest_all would report "store not
-- seeded", and the source would look broken for a reason nothing points at.
-- ---------------------------------------------------------------------------

INSERT INTO store (slug, name, website_url) VALUES
    ('asaxiy', 'Asaxiy', 'https://asaxiy.uz')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO schema_version (version) VALUES (3) ON CONFLICT (version) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Migration 4: radius.uz, the ninth source. Appended for the same reason
-- migration 3 was -- see the comment there.
-- ---------------------------------------------------------------------------

INSERT INTO store (slug, name, website_url) VALUES
    ('radius', 'Radius', 'https://radius.uz')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO schema_version (version) VALUES (4) ON CONFLICT (version) DO NOTHING;
