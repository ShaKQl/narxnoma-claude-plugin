---
name: narxnoma-maintain
description: Maintain the narxnoma repo (narxnoma-claude-plugin) — the Uzbek electronics price-fetch engine and its Claude Code plugin. Use at the start of any session in this repo, when adding or fixing a retailer source (uzum, alifshop, beemarket, idea, mediapark, olcha, texnomart, asaxiy, radius, glotr, openshop), changing the matcher, updating plugin skills or docs/parsers, regenerating the llms digests, or releasing/pushing to GitHub (ShaKQl/narxnoma-claude-plugin, public).
---

# narxnoma — maintainer skill

This repo is **public** (github.com/ShaKQl/narxnoma-claude-plugin, MIT). It holds the
engine (`narxnoma-crawler/`), the plugin skills users install (`skills/`), the canonical
per-store notes (`docs/parsers/`), a golden matcher corpus and an optional web app.
Layout: `docs/folder-map.md`. History and open items: `docs/CHANGELOG.md`.

## 1. Session start

1. `git status --short` and `git log --oneline -8`; `git fetch` and compare with
   `origin/main` before editing — the July–August build happened on another machine.
2. Read **Latest state** at the top of `docs/CHANGELOG.md`.
3. Touching a store → read `docs/parsers/<slug>.md` first (canonical, rebuild-grade).
   Touching the matcher → `docs/parsers/_matching-engine.md` and the passes in
   `docs/parsers/README.md`. Adding a store → plugin skill `adding-a-narxnoma-source`.

## 2. Invariants

- **Public repo.** Never commit `.env`, tokens, private catalogues, or any retailer's
  *own* internal data (the Ishonch storefront/warehouse notes are deliberately
  excluded — see `docs/parsers/README.md`). Recorded public catalogue responses are fine.
- `docs/parsers/` is canonical. Code and doc disagree → verify live, fix both in one commit.
- Never trade precision for recall. A transport check cannot validate a matcher; read
  the matched names. A new store's naming style is a new test corpus.
- `matching/` is pinned by the 14,860-row golden corpus (`narxnoma-seed/golden/`):
  measure before changing identity rules (`tests/matching/`).
- A store is complete only with: client + pure `parse()`, fixture, `tests/sources/test_<slug>.py`,
  live contract case, `SOURCES`, `EXPECTED_MIN_OFFERS`, an appended schema migration,
  DB-test slug lists, `docs/parsers/<slug>.md` + index row, `skills/fetch-<slug>`,
  README + `llms.txt` + manifests.
- Politeness: sequential, 0.3–0.6 s pause; a published rate limit gets a client floor
  (openshop 0.55 s). glotr only by grant at its `Crawl-delay`.

## 3. Quick path

```bash
cd narxnoma-crawler
python -m pip install --user -e ".[dev]"              # once: requests, psycopg, pytest, ruff, openpyxl
python -m pytest -q                                    # offline; expect 627 passed, 72 skipped
python -m pytest -q -m live tests/sources/test_contract_live.py -k <slug>
python -m ruff check --select E4,E7,E9,F,E501 <changed files>   # repo config = ruff defaults
python -m narxnoma.cli fetch --source <slug> --category <c> --limit 20
cd .. && python tools/regen_digests.py                 # after any docs/skills/engine change
```

Release: bump `.claude-plugin/plugin.json` `version`, add a CHANGELOG entry, commit,
`git push origin main`. The GitHub repo description lists the stores — keep it in sync
(`gh repo edit ShaKQl/narxnoma-claude-plugin --description …`).

## 4. Current state

- Eleven sources; plugin **1.2.0**; schema migration **6** (openshop).
- Offline suite 627 passed / 72 skipped / 12 deselected = 9 live + 3 `excel` (2026-10-22).
- `narxnoma/research/` (market research → analysable Excel workbook): canonical notes
  `docs/market-research.md` and `docs/excel-workbooks.md`; run `pytest -m excel tests/research`
  on a machine with desktop Excel after touching `workbook.py` or `excel/`. Never re-save a
  finished workbook through openpyxl (drops slicers / Data Model).
- Open: eight matcher gaps from openshop names (`docs/parsers/openshop.md` §8), not yet
  fixed in `matching/`; one pre-existing over-long line in `test_contract_live.py`.
- Downstream user: the Extractractor project (Ishonch pricing, private) vendors
  `narxnoma/sources` + `matching` DB-free and runs openshop research there. Changes to
  shared clients should be copied both ways.

Last updated: 2026-10-22.

## 5. Maintenance protocol

At the end of any session that changed the repo:
1. Add a dated entry to `docs/CHANGELOG.md` and refresh its **Latest state**.
2. Update affected `docs/parsers/*`, plugin skills, README tables, `llms.txt`.
3. Update §4 above and `Last updated`.
4. `python tools/regen_digests.py`; re-check `.gitignore` for new raw or secret files.
5. Commit with a descriptive message; push only when asked.
If a doc claim is corrected, fix it immediately, not at session end.
