# Daily price refresh and market report

Canonical note for `narxnoma-crawler/narxnoma/daily.py`. Two unattended jobs for the owner's
own machine, run by the OS scheduler. **No Claude session is involved**, and nothing about the
store's API (URL, token, field names) is in this repo — it lives in an env file outside it.

| job | when (Tashkent) | what |
|---|---|---|
| `python -m narxnoma.daily refresh` | 03:00 | re-sweeps every sweepable store × every category into the cache (`research_cache/`), ignoring cache age. Failures are listed in a Telegram note. |
| `python -m narxnoma.daily report` | 09:00 | pulls the store's admin catalogue → `products_<date>.csv` → `run_research` against the fresh cache → `market_analysis_<date>.xlsx` (+ `.json`) → Saved Messages |
| `python -m narxnoma.daily probe` | by hand | prints the catalogue response's field names and types (never values) and how the mapping reads them |

## Set-up on the PC

1. `pip install -e "narxnoma-crawler[excel]" telethon`
2. Copy `tools/daily/daily.env.example` to `%USERPROFILE%\.narxnoma-daily.env`, fill it in.
   `ECOM_TOKEN_FILE` should be the file the order-triage job keeps current; it is read on every
   run, so a rotated token needs no change here.
3. `python -m narxnoma.daily probe` — confirm name / price / category are found; if not, set
   `ECOM_FIELD_*`.
4. `python -m narxnoma.daily report --no-send` — builds today's file without sending.
5. `.\tools\daily\install-windows-tasks.ps1` — registers both tasks.

## How the two jobs avoid each other and the other Telegram jobs

- **One lock** (`daily.lock` in `NARXNOMA_DAILY_DIR`): `refresh` refuses to start while a job
  holds it; `report` waits up to 90 min for a still-running refresh, then gives up with a note.
  A lock older than 6 h is treated as left by a crash and taken over.
- **Cache age**: `report` accepts cache up to 30 h old (`NARXNOMA_MAX_AGE_H`), so the 03:00
  refresh is what it reads; if a store failed at 03:00 its older cache is used and the
  workbook's `fetched_at` shows it.
- **Telegram**: sends from a temporary **copy** of the session file, never logs in, deletes the
  copy (the same approach as the cube-status job, so the order listener's authorisation is not
  disturbed). If it collides with another send around 09:00 it retries up to 4× at 90 s.
- Failures (report crash, expired token, refresh stuck) are sent to Saved Messages as text, so
  a missing morning file always has an explanation.

## Behaviour worth knowing

- Products with **no category** cannot be matched (the matcher's identity model needs one); the
  caption of the Telegram message says how many. Map the store's categories in
  `research/targets.py:CATEGORY_ALIASES` if `probe` shows names that are not recognised.
- Inactive products are dropped by default (`ECOM_ONLY_ACTIVE=1`); the request still asks the
  API for `include_inactive=true` only if `ECOM_EXTRA_PARAMS` says so.
- The catalogue is paged until a short or empty page, or until a page repeats (a server that
  ignores `page`); more than 500 pages raises.
- Tests: `tests/test_daily.py` (offline, synthetic payloads). The real API and Telegram are
  exercised only by hand.
