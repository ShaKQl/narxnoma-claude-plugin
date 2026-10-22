# Market research: a product list in, an analysable workbook out

Canonical note for `narxnoma-crawler/narxnoma/research/`. Read it before changing that
package. The Excel engineering behind the workbook is in
[excel-workbooks.md](excel-workbooks.md).

## What it answers

*"Here is a list of products. What does every market charge for them, and where do we
stand?"* — and it hands back a workbook you can **work in**, not a picture of the numbers:
a small database (Excel Tables), formulas that follow your edits, a heat map that is
conditional formatting, and real PivotTables over the database.

Three tools, three questions — pick by the question:

| | `fetch` | `research` (this) | `cycle` (Postgres pipeline) |
|---|---|---|---|
| Answers | "what is on this store's shelf?" | "what do the markets charge for *my* list?" | "what is the canonical price of everything, continuously?" |
| Input | a source + category or query | a product list (xlsx / csv / txt) | none (sweeps everything) |
| Output | JSON lines | `.xlsx` + `research.json` | PostgreSQL |
| Needs | `requests` | `requests`, `openpyxl`; Excel optional | PostgreSQL |

## Quick start

```bash
pip install -e "narxnoma-crawler[excel]"             # adds openpyxl
cd narxnoma-crawler

python -m narxnoma.research run --targets products.xlsx --out research.xlsx
python -m narxnoma.research run --targets list.txt --category smartphones \
        --sources uzum,olcha,texnomart --out phones.xlsx
python -m narxnoma.research workbook --from research.json --out research.xlsx   # no fetching
python -m narxnoma.research check research.xlsx                                  # Excel recalculates, reports errors
```

`run` writes `research.json` next to the workbook (override with `--json`). Rebuilding a
workbook from it costs no requests, so a change to the workbook layout, the Settings
defaults or a baseline never needs a re-crawl.

### Input

| file | shape |
|---|---|
| `.xlsx` / `.xlsm` | first sheet, header row |
| `.csv` | UTF-8 (BOM ok), delimiter sniffed (`, ; tab`) |
| `.txt` | one name per line; `name;price` or `name<TAB>price`; `#` comments |

Columns are found by header name, case-insensitively (`targets.ALIASES`): **name**
(`Product`, `Product Name`, `Товар`, `Наименование`, `Mahsulot`…), **price** (`Our price`,
`Наша цена`, `Narx`…), **category** (`Category`, `Категория`…), **currency** (`UZS` default,
`USD` converted at the central-bank rate fetched live, or `--usd-rate`), **note**. *Any other
column is kept* as an extra column on `Products` — your own brand / supplier / segment
columns become pivot dimensions for free.

Only the name is required. With no price the baseline falls back to the market median.
A category is a narxnoma slug (`smartphones televisions laptops acs fridges washers ovens`);
`targets.CATEGORY_ALIASES` maps RU/UZ/EN words to it. A product with no category (and no
`--category`) is **not matched** — the matcher's identity model depends on it — and is
reported.

## The pipeline

1. **Collect** (`collect.py`). Every sweepable source is swept once per category present in
   the list and cached for 24 h in `database/research_cache/<source>__<category>.json`
   (`--max-age-h`, `--force`). Sweeping is the point: it gives every product the same
   candidate pool and lets a price be **re-matched without re-fetching**. A failed sweep
   raises inside the source and is **caught per (source, category)**: it is written to that
   market's Note, the market's `fetched_at` stays empty, the run continues. A half-swept
   catalogue is never recorded as a success, and a cache file is written atomically so a
   crash cannot leave a truncated one. Search-only sources (`mediapark`) get one query per
   product, nearly verbatim (only the leading category noun is dropped: a ranking
   autocomplete needs the RAM/storage and colour words to rank the exact variant). **glotr
   is excluded by default** — its robots.txt forbids crawling and it is used only by grant
   at its `Crawl-delay` (`docs/parsers/glotr.md`); name it in `--sources` deliberately.
2. **Match** (`match.py`). The shared matcher, unchanged: brand, model, RAM and storage must
   match; colour is not identity except on iPhones. Targets are bucketed by brand first
   (a brand mismatch is a hard reject before anything else; unknown-brand listings are
   always considered). The accept threshold is per category: **30 for phones, 25 for
   everything else** — a television has no storage/RAM/identity-colour, so a *perfect*
   brand + bidirectional model-code match scores exactly 25, and 30 would empty the
   category. 25 is not looser: it still requires the model tokens to match in both
   directions.
3. **Keep every accepted offer.** Nothing is reduced at this layer. A marketplace with 20
   sellers contributes 20 rows; `Offers` is the database the analysis runs on.
4. **Build** (`workbook.py`), then **pivots** (`excel/`), then **verify**. In that order,
   and nothing may re-save the file through openpyxl afterwards.

### Known limits (read before quoting a result)

- The matcher is used as-is. Eight gaps that openshop's names exposed are documented, not
  fixed (`docs/parsers/openshop.md` §8): e.g. `iPhone 16 128GB (SIM + eSIM)` and
  `Samsung 55" Crystal UHD DU7100 ... (UE55DU7100UXUZ)` are rejected as the same product.
  Precision over recall: a miss shows as an empty cell, never as a wrong price. Fixing a
  gap needs a golden-corpus measurement first (`narxnoma-seed/golden/`).
- `Name delta` on `Offers` lists words present in one name but not the other. Non-empty is
  not an error; it is the row to read before quoting.
- A listing at an implausible price (outside 100 000 – 100 000 000 UZS) is dropped by the
  source client, so very cheap accessories and very expensive display units never appear.
- Categories outside the seven narxnoma knows are not matched.

## The workbook

| Sheet | What it is | Edit it? |
|---|---|---|
| `Start` | index with links, how to use | — |
| `Prices` | product × market grid: the **cheapest accepted offer per market**, as formulas over `tblOffers`; plus Baseline, Markets matched, min, median, Δ ours vs median, cheapest market. **The heat map.** | no — formulas |
| `Heatmap` | the same grid as % difference from the baseline, graded colour scale | no |
| `Pivot …` | PivotTables over `tblOffers` (see below) | drag fields freely |
| `Offers` | Excel Table **`tblOffers`** — one row per offer, every one kept. Pivot source. | add / delete rows |
| `Products` | Excel Table **`tblProducts`** — one row per product. **Yellow cells are inputs.** | edit Our price, Category |
| `Markets` | Excel Table **`tblMarkets`** — coverage, average delta, share cheaper than baseline, cheapest wins, freshness, the reason a market is empty; bar chart | no |
| `Links` | as-fetched snapshot, each price a hyperlink to its offer | no |
| `Settings` | `cfg_par` `cfg_mid` `cfg_sat` thresholds and `cfg_baseline` (`Our price` / `Market median`) | **yes** |
| `Notes` | definitions, per-market freshness, what an empty cell means | — |

### How edits propagate

`Products[Our price]` → `Products[Baseline]` → `Offers[Baseline]` → `Offers[Delta vs baseline]`
→ `Offers[Band]`, and → `Prices` baseline → heat-map colours, `Heatmap`, `Markets`.
Change a price of yours, flip `cfg_baseline` to `Market median`, tighten a threshold, or
**append a row to `tblOffers`** (the calculated columns fill themselves, the grid picks the
offer up): everything follows. This was verified in real Excel (see *Verification*).

### Definitions

- **Baseline** = your price if you gave one and `cfg_baseline` is `Our price`; otherwise the
  market median.
- **Market median** = median of one representative (cheapest) price per market, so a
  marketplace with many sellers does not outvote a single-shop retailer.
- **Delta vs baseline** = (market price − baseline) / baseline. **Negative = the market is
  cheaper than you.** (`Delta ours vs median` on `Prices` is the other way round:
  (our − median) / median, positive = you are dearer.)
- **Bands** (`Offers[Band]`, sort-prefixed so a pivot orders them): `1 Market much cheaper`
  ≤ −`cfg_sat` · `2 Market cheaper` ≤ −`cfg_mid` · `3 Market slightly cheaper` < −`cfg_par` ·
  `4 About equal` within ±`cfg_par` · `5…7` mirror image on the dear side. Defaults 2 % /
  10 % / 20 %.
- An **empty cell** means "no match found", never a price of zero.

### The heat map

Conditional formatting, never a baked fill. On `Prices`, seven rules over the market
block: a bold dark border on the cheapest price in each row, and six graded fills (three red
for a market cheaper than the baseline, three green for dearer). Each rule compares a cell
with **its own row's baseline** (`$N2`, absolute column, relative row) and reads its
thresholds from the named Settings cells. That is the one thing a built-in colour scale cannot
do (its endpoints come from the range, not from a per-row baseline) and a formula rule can.
`Heatmap` uses a real 3-colour scale whose end points are `-cfg_sat` / `0` / `+cfg_sat`.

Why this matters: a painted fill goes stale the moment a price is edited, and a wrong colour
is read faster than the number it contradicts. These cannot go stale, and they survive a
re-sort and a filter.

## Pivots — three tiers

| `--pivots` | Needs | Gives |
|---|---|---|
| `com` (auto when Excel is present) | Windows + desktop Excel | three PivotTables on one shared cache (Category×Market avg delta with a pivot-scoped colour scale; Product×Market cheapest price; Market×Band counts), **three slicers** (Category, Market, Band) that drive all of them, a **pivot chart**, neutral captions (no localised "Row Labels"), and — if this Excel has Power Pivot — a **Data Model** (below) |
| `ooxml` (auto when no Excel) | nothing | the same three PivotTables, written into the .xlsx package with `refreshOnLoad`; Excel builds them when the file is opened. No slicers, chart, Data Model; built-in number formats only |
| `none` | nothing | Tables + formulas + heat map; Insert > PivotTable > `tblOffers` does the rest |

### Data Model (`--model auto|yes|no`)

With `com`, the script **probes** `workbook.Model`. If present it loads `tblOffers`,
`tblProducts`, `tblMarkets` into the model, relates `Offers[Product] → Products[Product]` and
`Offers[Market] → Markets[Market]`, adds DAX measures (`Offers count`, `Median price`,
`Cheapest price`, `Avg delta`, `Share cheaper than baseline`) and a model-based PivotTable
(`Pivot model (DAX)`). If the probe fails — no Power Pivot, or any error — it prints
`MODEL unavailable: <reason>` and the workbook keeps the flat pivots: **flat is the fallback,
nothing is lost** (`--model yes` fails loudly instead). Both are present when the model works,
so you can compare.

## Verification

`python -m narxnoma.research check book.xlsx` opens the file in real Excel, recalculates
fully, and prints one line per sheet: formula-error cells, tables, pivots, conditional-format
rule counts, slicers. `run` / `workbook` call it automatically when Excel is present and exit 1
on any error cell. Why: openpyxl writes formulas it cannot evaluate, so a `#NAME?` is invisible
until a person opens the file.

What was verified on 2026-10-22 (real Excel 16, 25 synthetic products × 10 markets, 230
offers, and a live 8-product × 4-market run):

- 0 formula-error cells on all sheets; the file reopens with the right counts of tables,
  pivots, slicers.
- Every `Prices` cell, median, baseline, `Delta vs baseline`, cheapest flag, band and every
  `Markets` figure matched an **independent Python recomputation** (0 mismatches).
- Pivot and DAX figures were **spot-checked** against the same recomputation (category ×
  market averages, a market's grand total, offer counts, share cheaper than baseline, a band
  count); the whole pivot body was not compared cell by cell.
- Edits propagate: our price, the `Market median` switch, the thresholds and an appended
  `tblOffers` row each changed the displayed colours / bands as expected.
- The raw-OOXML pivots open and populate on open, with no manual refresh.

`pytest -m excel tests/research` repeats the Excel-side checks on any machine that has Excel;
the default `pytest` run skips them.

## Requirements

- Python ≥ 3.11, `requests`, `openpyxl ≥ 3.1` (`[excel]` extra).
- `MINIFS` / `MAXIFS` (used by `Prices`, `Products`, `Offers`) need **Excel 2019 / Microsoft
  365** or LibreOffice. They are written with the `_xlfn.` prefix; without it Excel shows
  `#NAME?` until a cell is re-entered.
- COM tier: Windows, desktop Excel, PowerShell. Data Model: an Excel with Power Pivot.
- Without Excel the formulas still work when a person opens the file, but cached values are
  absent, so a previewer or pandas shows blanks. Run `check --save` (needs Excel) to bake the
  calculated values in.

## Where things are

| File | Role |
|---|---|
| `research/targets.py` | read the product list; alias tables |
| `research/collect.py` | sweep + cache, search-only, market order, failure notes |
| `research/match.py` | brand-bucketed matching, category thresholds, name delta |
| `research/model.py` | `Target` / `Offer` / `Research`, JSON round-trip |
| `research/run.py` | `run_research`: collect → match; CBU USD rate |
| `research/workbook.py` | the workbook (openpyxl): tables, formulas, heat map, Settings, Notes |
| `research/build.py` | `make_workbook`: workbook → pivots → verify |
| `research/excel/pivots.ps1` / `pivots.py` | COM: pivots, slicers, chart, Data Model probe |
| `research/excel/ooxml_pivot.py` | raw-OOXML pivots, no Excel |
| `research/excel/verify.ps1` | Excel recalculates and reports errors, tables, pivots, fills |
| `tests/research/` | offline tests; `-m excel` for the Excel-side ones |
