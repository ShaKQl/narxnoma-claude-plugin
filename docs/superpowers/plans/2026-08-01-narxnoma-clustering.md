# Narxnoma Clustering & Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the offers already in Postgres into canonical products with trustworthy prices — so that for the first time the platform can answer "what does this exact phone cost, and where".

**Architecture:** Three new pipeline stages between harvest and the web layer. `extract` turns each offer's `name_raw` into features using Plan 1's matching library. `cluster` assigns each offer to a canonical `variant`, or parks it in `unresolved_offer` when the identity is ambiguous. `aggregate` recomputes per-variant price rollups, including the uzum multi-seller spread. Every stage is pure or database-only; none touches the network except mediapark's targeted Pass B.

**Tech Stack:** Python 3.11+, `psycopg[binary]` 3.x, PostgreSQL 16, pytest. Plan 1's `narxnoma.matching` is the identity authority and is reused, never reimplemented.

## Global Constraints

- Python 3.11 or newer. `narxnoma/matching/**` stays stdlib-only; a test enforces it.
- **Colour is a hard identity field. Unknown colour never equals any colour.**
- **RAM is identity only for brands that publish it** (`BRANDS_WITHOUT_PUBLISHED_RAM`). Requiring it for Apple would make every iPhone unkeyable.
- **Never guess.** An offer whose partial key matches two or more canonical variants goes to `unresolved_offer` with a reason. Zero matches also parks it. Attaching it anyway, and letting it set a headline price, is the single defect this platform exists to avoid.
- **Canonical products are permanent identities; offers are temporary observations.** Specifications belong to variants, prices to offers.
- Display names are **generated from the key**, never copied from a retailer — that is what makes duplicates structurally impossible.
- `raw_offer` stays append-only. Nothing in this plan writes to it.
- Tests use `NARXNOMA_TEST_DSN`, never `NARXNOMA_DSN`. A guard refuses to truncate a database whose name lacks `test`.
- `docs/parsers/` is the source of truth for retailer behaviour and is corrected in the same commit as any behaviour change.

---

## File Structure

```
narxnoma-crawler/
  narxnoma/
    db/
      schema.sql                    + variant, variant_price, unresolved_offer (appended, see Task 1)
      repository.py                 + variant/rollup/unresolved accessors
    pipeline/
      extract.py                    offer row -> Features            (pure)
      cluster.py                    Features -> variant_id | unresolved
      aggregate.py                  variant_price rollups, uzum spread
      backfill.py                   mediapark Pass B, previous cycle's variants
      quality.py                    unresolved rate, clustering coverage
    cli.py                          + `cluster`, `aggregate`, `quality` subcommands
  tests/
    pipeline/test_extract.py  test_cluster.py  test_aggregate.py
                              test_backfill.py test_quality.py
```

---

### Task 1: Schema for canonical products

**Files:**
- Modify: `narxnoma-crawler/narxnoma/db/schema.sql`
- Test: `narxnoma-crawler/tests/db/test_schema_variants.py`

**Interfaces:**
- Consumes: the existing `store`/`offer` tables.
- Produces: `variant`, `variant_price`, `unresolved_offer` tables; `offer.variant_id` becomes a real foreign key.

**Read `schema.sql`'s header comment first.** It states the rule for changing this file: never edit an existing `CREATE TABLE` to add or alter a column, because `CREATE TABLE IF NOT EXISTS` is a no-op on a database that already has the table — the change would apply on a fresh database and silently not apply in production. **Append** your migration at the bottom and bump `schema_version`.

- [ ] **Step 1: Write the failing test**

`tests/db/test_schema_variants.py`:

```python
import pytest

pytestmark = pytest.mark.db


def test_variant_tables_exist(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = 'public'
               AND table_name IN ('variant', 'variant_price', 'unresolved_offer')
             ORDER BY table_name
        """)
        assert [r[0] for r in cur.fetchall()] == ["unresolved_offer", "variant", "variant_price"]


def test_variant_slug_is_unique(db_conn):
    import psycopg
    with db_conn.cursor() as cur:
        for _ in range(2):
            cur.execute(
                "INSERT INTO variant (brand, model_tokens, ram_gb, storage_gb, color,"
                " sim_kind, display_name, slug, category)"
                " VALUES ('honor', ARRAY['x9d'], 12, 256, 'black', 'dual',"
                "         'Смартфон Honor X9D 12/256 ГБ, Черный',"
                "         'honor-x9d-12-256-black', 'smartphones')",
            )
            if _ == 0:
                continue
    # the second insert must have failed
```

Rewrite that second test properly: insert once, then assert a second insert of the same `slug` raises `psycopg.errors.UniqueViolation`. Add tests that `offer.variant_id` accepts a real variant id and rejects a random uuid (foreign key), and that `unresolved_offer` requires a non-empty `reason`.

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && python -m pytest tests/db/test_schema_variants.py -v`
Expected: FAIL — the tables do not exist.

- [ ] **Step 3: Append the migration to `schema.sql`**

```sql
-- ---------------------------------------------------------------------------
-- Migration 2: canonical products. Appended, never edited into the tables
-- above -- see the header comment.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS variant (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand         text NOT NULL,
    model_tokens  text[] NOT NULL,
    ram_gb        integer,                 -- NULL is legitimate: Apple omits RAM
    storage_gb    integer NOT NULL,
    color         text NOT NULL,           -- hard identity field, never NULL
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

CREATE TABLE IF NOT EXISTS variant_price (
    variant_id    uuid PRIMARY KEY REFERENCES variant(id) ON DELETE CASCADE,
    min_price     bigint NOT NULL,
    min_store_id  uuid REFERENCES store(id),
    min_offer_id  uuid REFERENCES offer(id),
    median_price  bigint,
    max_price     bigint,
    offer_count   integer NOT NULL DEFAULT 0,
    store_count   integer NOT NULL DEFAULT 0,
    computed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS unresolved_offer (
    offer_id       uuid PRIMARY KEY REFERENCES offer(id) ON DELETE CASCADE,
    reason         text NOT NULL CHECK (reason <> ''),
    candidate_ids  uuid[] NOT NULL DEFAULT '{}',
    recorded_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS unresolved_reason ON unresolved_offer (reason);

ALTER TABLE offer
    ADD CONSTRAINT offer_variant_fk
    FOREIGN KEY (variant_id) REFERENCES variant(id) ON DELETE SET NULL;

INSERT INTO schema_version (version) VALUES (2) ON CONFLICT (version) DO NOTHING;
```

`ADD CONSTRAINT` is not idempotent. Wrap it so a second run is a no-op:

```sql
DO $$ BEGIN
    ALTER TABLE offer ADD CONSTRAINT offer_variant_fk
        FOREIGN KEY (variant_id) REFERENCES variant(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && python -m pytest tests/db -v`
Expected: PASS, including the pre-existing migration tests.

- [ ] **Step 5: Prove idempotency against a database that already has data**

Run `migrate()` twice against a database holding offers, and confirm no error and no data loss. This is the failure mode the header comment warns about; prove it rather than assume it.

- [ ] **Step 6: Commit**

```bash
git add narxnoma-crawler/narxnoma/db/schema.sql narxnoma-crawler/tests/db/test_schema_variants.py
git commit -m "feat(db): add variant, variant_price and unresolved_offer tables"
```

---

### Task 2: Fix `_SKU_MIN_LEN`, measured against the corpus

**Files:**
- Modify: `narxnoma-crawler/narxnoma/matching/features.py`
- Modify: `docs/parsers/_matching-engine.md`
- Test: `narxnoma-crawler/tests/matching/test_features.py`

**Do this before clustering.** A model token wrongly discarded is an identity silently lost, and clustering would bake that loss into permanent canonical products.

**The bug.** `extract_features` skips alphanumeric tokens of length ≥ 5 as SKU codes. `reno15` is seven characters, so `OPPO Reno15 5G 12/512GB` yields **empty model tokens**. Two measured consequences: `variant_key` returns `None`, so every OPPO Reno is unkeyable and silently excluded; and `score_match(Reno15, Reno14) = 45`, above the accept threshold of 30, so two generations take each other's prices.

The rule exists for real reasons — `SM-A376EZADSOZ` and `A075F` are catalogue codes that must not become identity. The question is where the boundary belongs.

- [ ] **Step 1: Measure before changing anything**

Write a throwaway script over `narxnoma-seed/golden/audit_*.json` (14,860 real candidate rows) that reports, for each candidate `_SKU_MIN_LEN` from 5 to 9 and for a rule based on digit-count instead of length: how many rows change accept/reject versus the golden set, and how many distinct names gain or lose model tokens. **Report the table before choosing.** Do not pick a value and then justify it.

- [ ] **Step 2: Write the failing tests**

```python
def test_short_model_designators_survive():
    assert "reno15" in extract_features("OPPO Reno15 5G 12/512GB White").model_tokens
    assert "a17" in extract_features("Samsung Galaxy A17 6/128 Black").model_tokens


def test_reno_generations_do_not_match_each_other():
    a = extract_features("OPPO Reno15 5G 12/512GB White")
    b = extract_features("OPPO Reno14 5G 12/512GB White")
    assert score_match(a, b) == HARD_REJECT


def test_catalogue_codes_are_still_skipped():
    # These are the reason the rule exists. They must not become identity.
    assert "sm-a376ezadsoz" not in extract_features("Samsung SM-A376EZADSOZ 8/256").model_tokens
    assert "a075f" not in extract_features("SAMSUNG SM-A075F A07 4/64").model_tokens
```

- [ ] **Step 3: Run to verify failure** — the first two fail, the third passes.

- [ ] **Step 4: Implement whichever rule your measurement supports**, and re-run the golden regression (`tests/matching/test_golden.py`). Agreement must stay at or above its floor. If your change drops it, the change is wrong — measure again rather than lowering the floor.

- [ ] **Step 5: Correct `docs/parsers/_matching-engine.md`** — the SKU-skip section must state the new rule, why the old one lost `reno15`, and the measurement that chose the boundary.

- [ ] **Step 6: Commit** — `fix(matching): stop discarding short model designators as SKU codes`

---

### Task 3: The `extract` stage

**Files:**
- Create: `narxnoma-crawler/narxnoma/pipeline/extract.py`
- Test: `narxnoma-crawler/tests/pipeline/test_extract.py`

**Interfaces:**
- Consumes: `narxnoma.matching` (`extract_features`, `sim_kind`, `variant_key`, `partial_key`).
- Produces: `OfferIdentity` frozen dataclass carrying `offer_id, features, sim_kind, key, partial`; and `identify(offer_row) -> OfferIdentity`.

This stage is **pure** — a database row in, a structure out, no I/O. That is what makes clustering testable without a database.

The SIM kind comes from the offer's `name_raw` **and** from source-specific data in the raw payload: uzum records SIM characteristics that never reach the name. Accept an optional `raw` dict and prefer an explicit SIM signal in it over one inferred from the name.

- [ ] **Step 1: Write the failing tests** covering: a complete name yields a full `key`; a name missing RAM for a non-Apple brand yields `key is None` and a usable `partial`; an Apple name with no RAM still yields a **full** key; an unmappable colour yields no key; and an explicit eSIM signal in `raw` beats the name.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.** Keep it thin — all the judgement lives in Plan 1's library; this stage only adapts a database row to it.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Run it across the real database** and report how many current offers yield a full key, a partial key, or nothing, broken down by store. Those three numbers are the input to every decision in Task 4.
- [ ] **Step 6: Commit.**

---

### Task 4: The `cluster` stage — where the promise is kept

**Files:**
- Create: `narxnoma-crawler/narxnoma/pipeline/cluster.py`
- Modify: `narxnoma-crawler/narxnoma/db/repository.py`
- Test: `narxnoma-crawler/tests/pipeline/test_cluster.py`

**Interfaces:**
- Consumes: `OfferIdentity` (Task 3), `display_name`/`slug`/`resolve_partial` from `narxnoma.matching`.
- Produces: `cluster_offers(conn, identities) -> ClusterResult` with `attached, created_variants, unresolved` counts; repository functions `upsert_variant`, `attach_offer_to_variant`, `record_unresolved`, `load_variant_keys`.

**This task is the entire competitive thesis.** Everything else is plumbing around it.

Algorithm:
1. Offers with a **full key** create or find their canonical variant. `slug` is the natural key — it is a deterministic function of the identity, so `ON CONFLICT (slug) DO NOTHING RETURNING id` makes creation idempotent and race-free.
2. Offers with a **partial key** are resolved against the variants that now exist, via `resolve_partial`. Exactly one compatible candidate attaches. **Zero or two-or-more parks the offer** in `unresolved_offer` with a reason naming which case it was and the candidate ids.
3. Offers with **no usable identity** park with the reason from `why()`.

Order matters: full keys must be processed before partials in the same run, or a partial will fail to resolve against a variant that this very run was about to create.

- [ ] **Step 1: Write the failing tests.** The load-bearing ones:

```python
def test_two_spellings_of_one_phone_become_one_variant():
    # "Cosmic orange" and "Cosmic Orange" are two products on a competitor's
    # site, splitting the offer pool so both pages show a wrong minimum.
    ...


def test_ambiguous_partial_is_parked_not_guessed():
    # 8/256 and 12/256 both exist; an offer stating only 256 matches both.
    # Attaching it anyway is the defect this platform exists to avoid.
    ...


def test_partial_with_exactly_one_candidate_attaches():
    ...


def test_esim_only_and_dual_are_different_variants():
    ...


def test_clustering_is_idempotent():
    # Running twice must not duplicate variants or double-attach offers.
    ...
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement**, with `upsert_variant` using `ON CONFLICT (slug) DO NOTHING`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Run against the real database.** Report: variants created, offers attached, offers unresolved, and the unresolved reasons ranked by frequency. **Then read the top twenty unresolved offers by hand and say what they are.** A high unresolved rate is either a matcher weakness or genuine retailer noise, and only reading them tells you which.
- [ ] **Step 6: Commit.**

---

### Task 5: The `aggregate` stage

**Files:**
- Create: `narxnoma-crawler/narxnoma/pipeline/aggregate.py`
- Test: `narxnoma-crawler/tests/pipeline/test_aggregate.py`

**Interfaces:**
- Consumes: `robust_median` from `narxnoma.matching.stats`.
- Produces: `recompute_variant_prices(conn) -> int`; `uzum_spread(conn, variant_id) -> Spread | None` with `min_price, median_price, max_price, seller_count`.

Rules:
- Only **in-stock** offers set `min_price`. An out-of-stock offer is recorded but must never become the headline price.
- `min_store_id` and `min_offer_id` record *which listing* the headline price came from. That provenance is the product feature — it is what lets a product page quote the retailer's own wording beside the number.
- uzum is multi-seller: many sellers list one variant. Use `robust_median` (IQR-stripped) so a mis-listed accessory cannot drag the median, and report `seller_count`.

- [ ] Steps 1–4 as usual: failing tests covering an out-of-stock offer never becoming the minimum, provenance columns populated, a single-offer variant getting min == median == max, and IQR stripping removing an outlier; then implement and pass.
- [ ] **Step 5:** run against the real database and report the ten cheapest variants with their store and offer count. Open two in a browser and confirm the price matches.
- [ ] **Step 6: Commit.**

---

### Task 6: mediapark Pass B

**Files:**
- Create: `narxnoma-crawler/narxnoma/pipeline/backfill.py`
- Test: `narxnoma-crawler/tests/pipeline/test_backfill.py`

mediapark cannot be swept — `can_sweep` is `False` and `sweep()` raises. It is reached only by searching for products we already know about, which is why it was deferred until variants exist.

Per the design spec, Pass B reads the variant list from the **previous** cycle, not the current one. Feeding it this cycle's clustering output would make the pipeline cyclic for one source's benefit. The cost is that a brand-new phone gets its mediapark offer one cycle late.

Query mediapark with each variant's `display_name`, and — per `docs/parsers/mediapark.md` — keep the query nearly verbatim including the memory figure and colour, because that endpoint ranks rather than filtering and stripping terms measurably worsens recall.

- [ ] Failing tests with a fake source: the correct query string is built from a variant; results are written as offers; a variant with no match records nothing and does not raise; and the run is bounded so a large catalogue cannot make one cycle unbounded.
- [ ] Implement, pass, then run for real against a handful of variants and report the hit rate.
- [ ] Commit.

---

### Task 7: Quality report

**Files:**
- Create: `narxnoma-crawler/narxnoma/pipeline/quality.py`
- Modify: `narxnoma-crawler/narxnoma/cli.py`
- Test: `narxnoma-crawler/tests/pipeline/test_quality.py`

`unresolved_offer`'s row count is a **quality signal about the matcher**, and it only means something if it is watched. Produce `quality_report(conn)` carrying: total offers, attached, unresolved, unresolved rate, the top reasons with counts, variants with only one offer, and variants whose min and median diverge by more than 12% — that last one is how Plan 1's notes caught a card-price-versus-SKU-price bug, and it is worth surfacing permanently.

Alert when the unresolved rate exceeds **5%**, and make `cli quality` exit non-zero then, for the same reason `report` does: a pipeline that "succeeded" while failing to identify a fifth of its offers has not succeeded.

- [ ] Failing tests for each metric and for the exit code; implement; pass; run for real and report every number.
- [ ] Commit.

---

### Task 8: Wire the pipeline together

**Files:**
- Modify: `narxnoma-crawler/narxnoma/cli.py`, `narxnoma/pipeline/harvest.py`
- Test: `narxnoma-crawler/tests/test_cli.py`

Add `cluster`, `aggregate` and `quality` subcommands, plus a `cycle` command running harvest → extract → cluster → aggregate → quality in order, with each stage's failure recorded and the exit code reflecting the worst outcome.

Keep stage isolation: a clustering failure must not lose the harvest that preceded it.

- [ ] Failing tests with fakes; implement; pass.
- [ ] **Run a full real cycle** and report every stage's numbers.
- [ ] Commit.

---

## Self-Review

**Spec coverage.** This plan implements the design spec's §5 (canonical model, variant key, never-guess resolution, generated display names), §6's remaining tables, §4's `extract`/`cluster`/`aggregate` stages and Pass B, and the uzum spread from §7's feature list. The web layer is Plan 4.

**Deliberately out of scope, and why.** The crawler debt recorded in `.superpowers/sdd/progress.md` — hoisting the six-times-duplicated pagination loop, per-page error handling, `brand_queries` doubling as a crawl frontier, texnomart's missing category filter, and a `pg_try_advisory_lock` single-instance guard — is **Plan 2b**, a separate short hardening plan. Mixing it in here would make a clustering plan that also rewrites seven clients, and neither half would be reviewable.

**Sequencing note.** Task 2 comes before clustering deliberately. Clustering writes permanent canonical identities; a model token wrongly discarded at that moment becomes a permanently wrong catalogue, not a transient error.

## Follow-on plans

- **Plan 2b — crawler hardening.** The deferred source-layer items above, plus recording an Apple-query uzum fixture and scheduling the `live` contract tests.
- **Plan 4 — web.** Next.js against the Narxnoma design, reading `variant`, `variant_price` and `offer`.
