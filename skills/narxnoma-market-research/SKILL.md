---
name: narxnoma-market-research
description: Use when asked to research a list of products against Uzbek retailers (uzum, alifshop, beemarket, idea, mediapark, olcha, texnomart, asaxiy, radius, openshop), compare our prices with the market, or deliver an Excel file the user can analyse, pivot and heat-map rather than a static table.
---

# narxnoma market research

A product list in; an **analysable** workbook out — Excel Tables as a database, formulas that
follow edits, a conditional-formatting heat map, real PivotTables. Canonical doc:
`docs/market-research.md`; the Excel engineering: `docs/excel-workbooks.md` (and skill
`narxnoma-excel-workbooks`).

## Run it

```bash
pip install -e "narxnoma-crawler[excel]"          # once; openpyxl for the workbook
cd narxnoma-crawler
python -m narxnoma.research run --targets products.xlsx --out research.xlsx
python -m narxnoma.research run --targets list.txt --category smartphones --sources uzum,olcha --out p.xlsx
python -m narxnoma.research workbook --from research.json --out research.xlsx   # rebuild, no fetching
python -m narxnoma.research check research.xlsx                                  # Excel recalculates it
```

The list: `.xlsx` / `.csv` / `.txt`. Only a name is required. Useful columns: `Our price`
(UZS, or `Currency` = USD), `Category` (smartphones, televisions, laptops, acs, fridges,
washers, ovens — or the RU/UZ word), and **any extra column you want to pivot by** (brand,
supplier, segment): it becomes a column on `Products`.

## Decide before running

1. **Category.** A product with none is not matched. Pass `--category`, or put it in the file.
2. **Markets.** Default = all but glotr (robots.txt forbids; only by grant — name it
   deliberately). `mediapark` is search-only: one query per product.
3. **Pivots.** `--pivots auto` = Excel COM when Excel is installed (slicers, chart, Data Model
   if Power Pivot exists) else raw OOXML (pivots build on open; no slicers). `none` = tables +
   formulas only. Say which one you used.
4. **Excel version.** `MINIFS`/`MAXIFS` need Excel 2019 / 365.

## Rules when presenting results

- **Say what the workbook is**: a database + view; edit yellow cells on `Products` (Our price,
  Category) and thresholds on `Settings`; everything follows. Don't hand over a screenshot or
  CSV of the grid when the workbook exists.
- **Colour direction**: red = the market is *cheaper* than the baseline; green = dearer. Baseline
  = our price, else market median (`Settings!cfg_baseline`).
- **An empty cell is "no match", never zero.** Misses are the price of precision (brand, model,
  RAM and storage must match; colour is not identity except iPhone). Known matcher gaps
  (`docs/parsers/openshop.md` §8) show as misses, not wrong prices.
- **Read `Name delta` on `Offers` before quoting an outlier.** A plausible price is not a right
  one; the listing name is checkable.
- **Freshness**: each market's catalogue time is on `Markets` and `Notes`; a failed sweep is
  named there. Re-matching is free (24 h cache); `--force` refetches.
- **Verify, don't assume**: `run` / `workbook` call Excel's recalculation check when Excel is
  present and exit 1 on any formula error. Without Excel, say the file is unverified.
- Never re-save the finished file through openpyxl (drops slicers and the Data Model).

## Extending

New store → `adding-a-narxnoma-source` (it appears in research automatically once registered in
`SOURCES`; add it to `collect.MARKET_ORDER`). A new input alias → `targets.ALIASES` /
`CATEGORY_ALIASES`. Workbook layout → `research/workbook.py`; add or change a test in
`tests/research/test_research_workbook.py` (and run `pytest -m excel` on a machine with Excel).
