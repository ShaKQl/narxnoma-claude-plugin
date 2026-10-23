# Changelog

Read this at the start of a session to know what changed last and what state the
repo is in. Newest first. Older history is summarised per era from `git log`.

## Latest state (2026-10-23)

- **Eleven sources**: uzum, alifshop, beemarket, idea, mediapark, olcha, texnomart,
  asaxiy, radius, glotr, openshop. All sweepable except mediapark (search-only).
- Offline suite: **650 passed**, 72 skipped (need `NARXNOMA_TEST_DSN`), 12 deselected
  (9 live, 3 `excel` — need desktop Excel; they pass on the dev machine). openshop's live
  contract test passes.
- **Market research** (`narxnoma/research/`): a product list in, an analysable Excel
  workbook out — see `docs/market-research.md`.
- **Daily jobs** (`narxnoma/daily.py`, `docs/daily-report.md`): 03:00 price refresh and 09:00
  catalogue → research workbook → Telegram, run by the owner's OS scheduler.
  **Not on `main` yet**: merge `claude/gallant-pascal-y8au1g`, then pull on the PC.
- Plugin manifest version **1.2.0**.
- Open items:
  - `research`: the matcher gaps below limit recall on openshop names (iPhone `SIM + eSIM`,
    codes in parentheses); the Data Model tier is verified only on one Excel 16 build;
    raw-OOXML pivots have no slicers / chart / model; no cached values without Excel.
  - Eight matcher gaps that openshop's names exposed are documented, not fixed in
    `matching/` (`docs/parsers/openshop.md` §8). Each needs a golden-corpus
    measurement before it lands.
  - One pre-existing lint finding: an over-long line in
    `tests/sources/test_contract_live.py` (uzum case).
  - `docs/superpowers/NEXT-SESSION-PROMPT.md` is a handoff from the July build on
    another machine (`D:\ASUS\Desktop\narxnoma`); historical, not current.

## 2026-10-23 — daily report: why no morning file arrived, and two fixes

- **Status found**: the daily jobs (`d9cfffd`) were committed only on the unmerged branch
  `claude/ecstatic-pascal-eohvyu`, not on `main`. A PC that runs `main` has no
  `narxnoma.daily`, so the 09:00 task exits before it logs anything and sends nothing. This
  branch now carries that commit plus the fixes below; it still needs a merge to `main` and
  a pull on the PC.
- **Fix: inline comments in the env file.** `tools/daily/daily.env.example` had
  `TG_SESSION=… # comment`, and `load_env` kept the comment as part of the path. The report
  then built the workbook, failed to send it four times (6 min), and the failure notice failed
  for the same reason: nothing in Telegram, only `report.log`. `load_env` now ends unquoted
  values at ` #`; the example puts the comment on its own line.
- **Fix: Telegram pre-flight.** `report` checks `TG_SESSION` / `TG_API_ID` / `TG_API_HASH`,
  the session file and telethon before fetching anything, and logs the reason.
- Tests: `tests/test_daily.py` 18 → 22, including the first end-to-end `job_report` run
  (offline: catalogue → csv → research → workbook → one send). Suite 650 passed / 72 skipped.
- `docs/daily-report.md`: a "no file this morning" checklist (module present, Task Scheduler
  result, `report.log`, workbook built but not sent).
- Still **not verified live**: the real catalogue response and the Telegram send (this
  container cannot reach the store or Telegram); run `probe` and `report --no-send` on the PC.

## 2026-10-22 — unattended daily refresh and morning report

- **New `narxnoma/daily.py`** (`python -m narxnoma.daily refresh|report|probe`): runs on the
  owner's PC from Task Scheduler, independent of any Claude session. `refresh` (03:00
  Tashkent) re-sweeps all stores into the research cache; `report` (09:00) pulls the store's
  admin catalogue (paged, bearer token re-read from a file each run), writes a dated
  `products_<date>.csv`, runs the research pipeline on the fresh cache, and sends
  `market_analysis_<date>.xlsx` to Telegram Saved Messages from a temporary copy of an existing
  user session. Failure notices go to the same place.
- `research/collect.py`: public `refresh_cache()` (forced, atomic, per-sweep failures).
- Nothing store-specific or secret is in the repo: URL, token file, field names, Telegram
  credentials live in an env file outside it (`tools/daily/daily.env.example`);
  `tools/daily/install-windows-tasks.ps1` registers the two tasks.
- One lock file keeps the jobs from overlapping; the report waits up to 90 min for a slow
  refresh. Tests: `tests/test_daily.py` (18, offline). **Not verified live**: the real catalogue
  response shape (use `probe`) and the Telegram send — both need the owner's machine; the
  build container's egress policy blocks the store and Telegram hosts.

## 2026-10-22 — market research: product list in, analysable workbook out

- **New package `narxnoma/research/`** (database-free; `openpyxl` via the `[excel]` extra),
  generalised from a private project's competitor-survey scripts: no retailer-internal data,
  no hard-coded paths. Entry: `python -m narxnoma.research run|workbook|check`, also
  `python -m narxnoma.cli research ...`.
  - `targets` (xlsx / csv / txt, header aliases RU/UZ/EN, extra columns kept), `collect`
    (24 h per-(source, category) sweep cache, atomic writes, per-source failure notes,
    search-only sources per product, glotr excluded by default), `match` (brand-bucketed;
    threshold 30 phones / 25 other categories; every accepted offer kept; name-delta audit),
    `run` (CBU USD rate for USD inputs), `model` (JSON round-trip: rebuild a workbook with
    no fetching).
  - **Workbook** (`workbook.py`): Excel Tables `tblOffers` / `tblProducts` / `tblMarkets`,
    a formula `Prices` grid, `Heatmap`, `Links`, `Settings` (named thresholds + baseline),
    `Notes`. Calculated columns fill rows a user adds. **Heat map = conditional formatting**
    with a per-row baseline and Settings-driven thresholds, so it follows edits and re-sorts.
  - **Pivots** (`excel/`): Excel COM (`pivots.ps1`) — three PivotTables on one cache, three
    slicers, pivot chart, neutral captions, and a Data Model with relationships + DAX
    measures when `workbook.Model` exists (probed; flat pivots are the fallback). Raw OOXML
    (`ooxml_pivot.py`) — pivots written into the package with `refreshOnLoad`, no Excel.
    `verify.ps1` — Excel recalculates and reports error cells, tables, pivots, slicers, CF
    rules and the displayed fill of named cells.
- Verified in real Excel 16: 0 formula errors; every grid / baseline / delta / band / market
  figure equals an independent Python recomputation; edits (our price, baseline switch,
  thresholds, an appended table row) propagate; raw-OOXML pivots populate on open. Live run:
  8 products × 4 markets (openshop, texnomart, olcha, mediapark), 4 offers matched (the rest
  correctly absent or lost to the known matcher gaps).
- Bugs found on the way (each now has a test or a note in `docs/excel-workbooks.md`): table
  column names must equal header cells; `_xlfn.` prefix for MINIFS/MAXIFS; undeclared `r:`
  namespace in hand-written `workbook.xml` fragments; openpyxl ≥ 3.1 hides chart axes;
  pivot captions follow the Excel UI language; the new `tests/research/conftest.py` shadowed
  the repo's `conftest` module (fixtures now in `tests/research/_synth.py`).
- Docs: `docs/market-research.md`, `docs/excel-workbooks.md`; skills
  `narxnoma-market-research`, `narxnoma-excel-workbooks`; README, `llms.txt`, folder map.
  pytest marker `excel` (deselected by default).

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
