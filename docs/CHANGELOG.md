# Changelog

Read this at the start of a session to know what changed last and what state the
repo is in. Newest first. Older history is summarised per era from `git log`.

## Latest state (2026-10-22)

- **Eleven sources**: uzum, alifshop, beemarket, idea, mediapark, olcha, texnomart,
  asaxiy, radius, glotr, openshop. All sweepable except mediapark (search-only).
- Offline suite: **584 passed**, 72 skipped (need `NARXNOMA_TEST_DSN`), 9 live
  deselected. openshop's live contract test passes.
- Plugin manifest version **1.1.0**.
- Open items:
  - Eight matcher gaps that openshop's names exposed are documented, not fixed in
    `matching/` (`docs/parsers/openshop.md` §8). Each needs a golden-corpus
    measurement before it lands.
  - One pre-existing lint finding: an over-long line in
    `tests/sources/test_contract_live.py` (uzum case).
  - `docs/superpowers/NEXT-SESSION-PROMPT.md` is a handoff from the July build on
    another machine (`D:\ASUS\Desktop\narxnoma`); historical, not current.

## 2026-10-22 — openshop.uz, the eleventh source; project onboarding

- **Added `openshop`** (`narxnoma/sources/openshop.py`), written and verified first in
  a downstream project on 2026-10-14 and ported here:
  - REST POST `get_products`, filters in the query string; full catalogue
    (5,723 products) in ~120 requests by walking the 11 top-level categories.
  - Traps documented and tested: `per_page` clamp at 48, deep-paging cap ~2,400,
    `link` field is the API host, `?lang=ru` URLs, page `<title>` carries the price,
    iPhone SIM variants as separate products.
  - Self-throttles at 0.55 s/request (API limit 120/min).
  - `ovens` = stoves, built-in ovens, hobs; microwaves and countertop mini-ovens
    excluded, matching what the other sources file under `ovens`.
  - Registered in `SOURCES`, `EXPECTED_MIN_OFFERS` (380, half of 769 measured),
    schema **migration 6** (store row), DB tests' slug lists.
  - Fixture `tests/fixtures/sources/openshop.json` (12 phones, incl. one discounted)
    and `tests/sources/test_openshop.py` (18 tests); live case in `test_contract_live.py`.
- Docs: `docs/parsers/openshop.md`; parser index row + **fourth pass** note (matcher
  gaps found by reading every matched name); README, `llms.txt`, plugin/marketplace
  manifests updated to eleven stores; skill `fetch-openshop`; umbrella skill
  `narxnoma-fetch` rules 6–7.
- Onboarding: `CLAUDE.md`, project-local skill `.claude/skills/narxnoma-maintain/`,
  this changelog, `docs/folder-map.md`, `tools/regen_digests.py` (digests
  regenerated as UTF-8; the previous `llms-full.txt` had Windows code-page mojibake).

## 2026-09-14 — Claude Code plugin

- Packaged the engine as a Claude Code plugin (`.claude-plugin/`), one skill per store
  plus `narxnoma-fetch` and `adding-a-narxnoma-source`.
- `cli fetch`: database-free JSON-lines output per source.
- `llms.txt` index and gitingest digests (`llms-full.txt`, `llms-engine.txt`).

## 2026-08-10 → 08-11 — beyond phones; sources eight to ten (Plan 5)

- Category-aware identity: TVs, laptops, ACs, fridges, washers, ovens. Non-phone
  sweeps by product noun, not brand; measured brand passes over the tripled catalogue.
- asaxiy (first HTML source), radius (Saleor GraphQL), glotr (classifieds, by grant).
- Third verification pass: populated-but-wrong fields (glotr pictures, past-last-page
  filler, uzum missing photos).
- `narxnoma-web` (Next.js) — search, comparison, stores health, RU/UZ UI.

## 2026-08-02 — clustering, aggregation, hardening (Plans 3, 2b)

- extract → cluster → aggregate → quality report; Pass B for search-only sources.
- `paginate()` with per-page retry; brand-query frontier; single-cycle lock.

## 2026-07-31 → 08-01 — seven retailer clients + harvest to Postgres (Plan 2)

- `Listing`/`Source` contract, polite HTTP layer, Postgres schema and repository.
- olcha, texnomart, idea, beemarket, alifshop, mediapark, uzum — each with a recorded
  fixture and parse tests; per-source coverage report and silent-shrinkage guard.

## 2026-07-27 — matching engine (Plan 1)

- Pure-stdlib matcher: normalise, colours (ru/uz/en), memory with Apple phantom-RAM
  guard, features, explainable `score_match`/`why`, variant keys, SIM kind, IQR median.
- Pinned against the 14,860-row live golden corpus (`narxnoma-seed/golden/`).
