---
name: narxnoma-excel-workbooks
description: Use when generating an Excel workbook that must be analysable, not static - PivotTables and slicers from Python, Excel Tables as a database, formulas that follow edits, conditional-formatting heat maps with per-row baselines, Data Model / DAX, or verifying a generated .xlsx in real Excel. Applies to narxnoma research workbooks and any openpyxl-built file.
---

# Analysable Excel workbooks from Python

Full write-up with every trap: `docs/excel-workbooks.md`. Working code:
`narxnoma-crawler/narxnoma/research/` (`workbook.py`, `excel/pivots.ps1`,
`excel/ooxml_pivot.py`, `excel/verify.ps1`). Verified against desktop Excel 16.

## The order (never break it)

`openpyxl builds` → `pivots / slicers / Data Model added` → `nothing re-saves via openpyxl`.
openpyxl cannot make a PivotTable and silently drops slicers and the Data Model on save.

## Checklist

1. **Database = Excel Tables** (one fact per row, flat long format). Table column names must equal
   the header cells — after `table._initialise_columns()` restore them, or Excel refuses the file.
   Calculated columns: `TableFormula(attr_text=…)` without `=`, `Tbl[[#This Row],[Col]]`, so added
   rows fill themselves. Header names without `( ) % # [ ]`.
2. **Knobs = defined names** on a `Settings` sheet (+ data validation). Inputs yellow, rest formulas.
3. **Formulas**: `_xlfn.MINIFS` / `_xlfn.MAXIFS` / `_xlfn.IFS` need the prefix (else `#NAME?`). `""` for
   no data, never 0. openpyxl writes no cached values → `fullCalcOnLoad`; to bake values let Excel save.
4. **Heat map = conditional formatting**, never painted fills. Per-row baseline = formula rule,
   relative row / absolute column, thresholds from names; both `fgColor` and `bgColor` on the fill;
   `stopIfTrue` for graded bands; `ColorScaleRule(start_type="formula", start_value="-cfg_sat" …)`
   for a scale driven by Settings. On a pivot: `AddColorScale(3)` + `ScopeType = 2`.
5. **COM pivots** (`pivots.ps1`): wrap every call in a retry for `0x800AC472`; `CalculateFull`
   first; `PivotCaches().Create(1, "tblX")`; ONE cache, many pivots, slicers via
   `SlicerCaches.Add2` + `.PivotTables.AddPivotTable`; number formats on the data field; set
   `CompactLayoutRowHeader/ColumnHeader` and `GrandTotalName` (they follow the UI language);
   optional steps in `Try-Step`; `Quit()` in `finally`.
6. **Data Model**: probe `$wb.Model`; `Connections.Add2(…, 7, $true, $false)` per table;
   `ModelRelationships.Add`, `ModelMeasures.Add` (DAX), pivot from `ThisWorkbookDataModel`. In a
   `try`; flat pivots stay as the fallback.
7. **No Excel**: `ooxml_pivot.py` injects cache + records + pivot parts with `refreshOnLoad="1"`.
   Declare `xmlns:r` on the `<pivotCache>` element (openpyxl's `workbook.xml` doesn't on the root).
   No slicers / chart / model.
8. **Verify in Excel**: `verify.ps1` (error cells per sheet, table/pivot/slicer/CF counts,
   `-Probe` displayed fill colour of named cells). Then recompute independently in Python and
   compare. Then render a sheet (`ExportAsFixedFormat` → PDF → PyMuPDF) and **look**. Then change an
   input through COM and re-probe.

## Don't

- Don't claim a workbook works because openpyxl wrote it. Say if Excel never opened it.
- Don't bake a colour that a rule can compute.
- Don't put a business's private figures in examples or fixtures in this public repo: synthetic
  rows only (`tests/research/_synth.py`).
