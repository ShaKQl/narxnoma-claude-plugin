# Plan 5 — Categories (TVs, laptops, ACs, fridges, washers, ovens)

STATUS: DESIGN + enabling migration landed (4b59153). Per-source sweep config
and matching identity are the executable work; each source change must be
fixture-verified per the SDD process (this is the correctness-critical part).

## Goal
Enlarge factual scale beyond smartphones: catalog televisions, laptops, air
conditioners, refrigerators, washing machines and ovens from all 7 sources,
with the same honesty guarantees (verbatim provenance, in-stock-only headline
price, colour/identity never guessed).

## Design decisions (2026-08-10, from probing the live code)
- **variant.category** already exists (default 'smartphones'). Category is the
  NEW top axis of identity: a variant key belongs to exactly one category.
- **Identity per category**:
  * smartphones: brand + model_tokens + ram_gb + storage_gb + color + sim_kind
    (unchanged — the memory-pair + colour + dual/esim identity).
  * NON-phone categories: brand + model_tokens + category. colour/sim_kind are
    NULL and NOT part of identity (a TV's black bezel doesn't distinguish
    products; requiring colour would make most TVs unkeyable). This is a
    deliberate, documented relaxation of the smartphone 'colour is hard
    identity' invariant — colour is only hard identity where it distinguishes.
  * storage_gb: keep NOT NULL in schema but for non-phones store the natural
    spec figure where one exists (e.g. laptop SSD 256/512/1024 GB; TVs/fridges
    may have no storage -> represent as NULL? schema has storage_gb NOT NULL).
    DECISION: relax storage_gb to nullable too (same migration style) so
    TVs/ACs/fridges with no memory are keyable by brand+model+category alone.
- **Matching**: the memory-pair+RAM/storage extraction is phone-flavoured but
  generic enough (brand + model tokens + optional specs). Non-phone identity
  key = (category, brand, model_tokens). The colour extraction stays passive
  (stored when present, never required, never part of identity for non-phones).
- **not_a_phone denylist** is PHONE-SWEEP policy only. Category sweeps must NOT
  run it (it would drop "телевизор"/"ноутбук" titles). Move the filter
  selection to the sweep/category level, not the parse level.

## Per-source category config (to VERIFY against a live response + fixture)
- **beemarket**: CATEGORY_SLUG per category (currently 'smartfony'). Verify
  sibling slugs: televizory, noutbuki, konditsionery, holodilniki,
  stiralnye-mashiny, dukhovki (exact spelling from the category endpoint).
- **idea**: category id per category (currently 55 = smartphones). Verify the
  id list for the six new categories from the category-tree response.
- **olcha**: CATEGORY url slug (currently 'telefony'). Verify slugs: televizory,
  noutbuki, konditsionery, holodilniki, stiralnye-mashiny, dukhovki.
- **alifshop**: facet `category` bucket display string (currently discovers
  'Смартфоны …'). Verify the TV/laptop/etc bucket names from the
  aggregations.category histogram and pass them through the same discover flow.
- **uzum**: category ids (currently 15271/15272 = smartphones). Verify the six
  category ids via makeSearch category facets; sweep by brand+category id.
- **texnomart**: search-query sweeps ('smartfon'). Extend to per-category query
  words ('televizor', 'noutbuk', ...). texnomart has no item category field, so
  this stays query-based + a per-category product-type ALLOWLIST (not the phone
  denylist).
- **mediapark**: Pass B is variant-driven (target = a key). Once non-phone
  variants exist, mediapark backfill follows automatically — no source change.

## Web
- /c/[category] already generic; add a category label map (Смартфоны, Телевизоры,
  Ноутбуки, Кондиционеры, Холодильники, Стиральные машины, Духовые шкафы).
- searchVariants: facets must be category-aware — RAM facet only for
  smartphones; colour facet only where colours exist; price bands for all.
- Cards: for non-phone variants show spec chips (diagonal/capacity) instead of
  RAM/SIM. display_name for non-phones = "Телевизор Samsung UE55 55\" ...".

## Migration (ALREADY LANDED in 4b59153)
color + sim_kind nullable. NEXT: also relax storage_gb to nullable (same
idempotent DROP NOT NULL) so spec-less appliances are keyable.

## Execution order (next session, fixture-verified per source)
1. Reconcile slug/id lists per source against a live response (probe script),
   record each in docs/parsers/<source>.md.
2. Matching: category-aware variant_key + display_name + slug; relax
   storage_gb; tests for non-phone identity (TV same model different colour =
   ONE variant; fridge capacity not conflated with phone storage).
3. Crawler: per-source category sweep plumbing (harvest --category), not_a_phone
   scoped to phones, expect_min_offers per category.
4. Fixtures + parse tests per source per category.
5. Web facets/pages; then a full cycle to refresh data.