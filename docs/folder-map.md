# Folder map

Read this when you need to know where something lives or what a file group is for.

## Top level

| Path | What it is | Notes |
|---|---|---|
| `README.md` | public front page: sources table, quick start, plugin install, rules | keep the source table in sync with `SOURCES` |
| `CLAUDE.md` | pointer for agent sessions working **on** this repo | loads `.claude/skills/narxnoma-maintain` |
| `.claude/skills/narxnoma-maintain/` | project-local skill: session checklist, invariants, current state | for maintainers; not part of the plugin |
| `skills/` | **plugin** skills shipped to users: `narxnoma-fetch`, `fetch-<slug>` ×11, `adding-a-narxnoma-source`, `narxnoma-market-research`, `narxnoma-excel-workbooks` | operational cards; `docs/parsers/` is canonical |
| `.claude-plugin/` | `plugin.json` (name, version, keywords) and `marketplace.json` | bump `version` when skills or sources change |
| `docs/parsers/` | canonical per-store notes + `_matching-engine.md` + `README.md` (index, verification passes) | rebuild-grade: a client must be rebuildable from its note alone |
| `docs/market-research.md` | canonical note for `narxnoma/research/`: pipeline, workbook anatomy, pivot tiers, verification | rebuild-grade; update with the code |
| `docs/excel-workbooks.md` | Excel engineering behind the workbook: Tables, formulas, conditional formatting, COM pivots, raw OOXML, verification, traps | |
| `docs/CHANGELOG.md` | what changed, newest first, plus "latest state" | update at the end of every session that changes the repo |
| `docs/deployment/` | local portable PostgreSQL; owner/server handover checklist | |
| `docs/superpowers/` | July–August design spec and plans 1–5; `NEXT-SESSION-PROMPT.md` | historical build record; paths in it point at the old machine |
| `narxnoma-crawler/` | the engine (Python ≥ 3.11) | see below |
| `narxnoma-seed/` | pre-production matcher and the 14,860-row golden corpus | reference data; never edit `golden/` by hand |
| `narxnoma-web/` | optional Next.js frontend over the Postgres catalogue | |
| `tools/` | maintenance scripts (see `tools/README.md`) | |
| `llms.txt` | LLM-oriented index of what to read first | hand-written |
| `llms-full.txt`, `llms-engine.txt` | gitingest digests | **generated** — `python tools/regen_digests.py` |
| `.gitingestignore` | what the full digest leaves out (fixtures, golden corpus, plans) | |

## `narxnoma-crawler/`

| Path | What it is |
|---|---|
| `narxnoma/sources/<slug>.py` | one client per store: `slug`, `can_sweep`, `sweep(category)`, `search(query)`, pure `parse(payload)` |
| `narxnoma/sources/base.py` | `Listing`, `coerce_price`, `try_build_listing`, `paginate`, price fences |
| `narxnoma/sources/http.py` | `polite_session`, `get_json`, `get_text`, `post_json` (pause after every request) |
| `narxnoma/sources/brand_queries.py` | crawl frontier for brand-query sources (idea, alifshop) |
| `narxnoma/matching/` | stdlib-only name → identity: normalize, colours, memory, features, categories, scoring, keys |
| `narxnoma/pipeline/` | harvest, extract, cluster, aggregate, quality, report (`EXPECTED_MIN_OFFERS`) |
| `narxnoma/research/` | product list → offers → analysable workbook: `targets` `collect` `match` `model` `run` `workbook` `build` `cli`; `excel/` = `pivots.ps1`/`pivots.py` (COM), `ooxml_pivot.py` (no Excel), `verify.ps1` |
| `narxnoma/db/schema.sql` | schema + append-only migrations (one per added store) |
| `narxnoma/cli.py` | `fetch` (no DB) · `harvest` · `cluster` · `aggregate` · `quality` · `report` · `cycle` |
| `tests/fixtures/sources/` | one recorded live response per store (public catalogue data) |
| `tests/sources/test_<slug>*.py` | offline parse tests from the fixture; `test_contract_live.py` (`-m live`) |
| `tests/db/` | need `NARXNOMA_TEST_DSN` (a disposable database); skipped otherwise |
| `tests/research/` | offline research tests (`_synth.py` = synthetic data, no private figures); `-m excel` needs desktop Excel |

## Naming conventions

- A store's slug is its domain stem (`openshop`, `texnomart`); the same slug names the
  client module, the fixture, the test module, the parser note, the `fetch-<slug>`
  skill, the `EXPECTED_MIN_OFFERS` key and the `store` row.
- Plans and specs are dated `YYYY-MM-DD-narxnoma-<topic>.md`.
- Each added store gets its own numbered schema migration, appended, never edited
  into migration 1 (production already ran it).
