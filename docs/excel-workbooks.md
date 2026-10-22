# Building analysable Excel workbooks

What it takes to generate an `.xlsx` that is a **tool**, not a screenshot of numbers: a
database you can pivot, formulas that follow edits, conditional formatting that stays honest,
and real PivotTables. Everything here was learned building
`narxnoma-crawler/narxnoma/research/` and was verified against real desktop Excel 16; the
failures are recorded because each one cost an hour. The workflow that uses it is
[market-research.md](market-research.md).

The techniques are generalised from tooling that builds PivotTables over an OLAP cube through
Excel automation (hidden Excel via COM, `GETPIVOTDATA`-linked report cells, recalculating a
file by letting Excel do it). No data from that work is in this repo.

## 1. The one ordering rule

```
openpyxl builds   →   pivots / slicers / Data Model are added   →   nothing re-saves through openpyxl
```

openpyxl can neither create a PivotTable nor keep a slicer: it warns *"Slicer List extension
is not supported and will be removed"* on load and silently drops slicers and the Data Model
on save. So the sheets, Tables, formulas, validation, conditional formatting and charts are
written first; the pivot step runs last and owns the file from then on. A pipeline that
loads the finished workbook with openpyxl "just to tweak a cell" destroys it.

## 2. Excel Tables are the database

- One Table per entity (`tblOffers`, `tblProducts`, `tblMarkets`), one fact per row. A flat
  long table (one row per product × market offer) is what a PivotTable wants; a wide grid is
  a *view* of it, built with formulas.
- **A Table column's name must equal its header cell's text, exactly.** `openpyxl` writes
  `Column1…ColumnN` if you call `table._initialise_columns()` (needed to attach
  `calculatedColumnFormula`) and Excel then refuses to open the file with an unhelpful
  "cannot get Open property" error. Restore the names from the header cells right after
  (`_calc_columns` in `research/workbook.py`).
- **Calculated columns** need `TableFormula(attr_text=...)` on the column so a row a person
  adds to the Table fills itself in. The formula text is stored *without* the leading `=`
  and uses `Table[[#This Row],[Col]]`.
- Keep referenced header names free of special characters (`( ) % # [ ] ' "`): they need
  escaping inside structured references. Spaces are fine. `Delta vs baseline`, not `Δ%`.
- Name the knobs: thresholds and switches live in a `Settings` sheet and are **defined
  names** (`cfg_sat`), so formulas, conditional-format rules and pivots read the same cell.
  Add data validation (decimal 0–1, a list) so a typo cannot produce nonsense.
- Inputs are visibly inputs (pale-yellow fill). Everything else is a formula.

## 3. Formulas: what the file format needs that the UI hides

- **`_xlfn.` prefix** for functions newer than Excel 2007 written through openpyxl:
  `_xlfn.MINIFS`, `_xlfn.MAXIFS`, `_xlfn.IFS`, `_xlfn.XLOOKUP`… Without it the cell shows
  `#NAME?` until someone re-enters it. `COUNTIFS`, `SUMIFS`, `AVERAGEIFS`, `IFERROR`,
  `AGGREGATE` are fine bare. A test asserts no bare `MINIFS` is ever written.
- openpyxl writes **no cached values**. Set `fullCalcOnLoad` so Excel calculates on open, and
  know that a previewer, pandas or LibreOffice-less reader sees blanks. To bake values in,
  let Excel save the file (`verify.ps1 -Save`).
- A SUMPRODUCT of `(col=x)/COUNTIFS(col,col, …)` gives a distinct count in every Excel
  version; `INDEX(range,0,MATCH(name,header,0))` returns a whole column by header name,
  which is how one formula fills a table row per market.
- Use `""` (not 0) for "no data"; `COUNT`, `MEDIAN`, `AVERAGE` ignore text. Never write 0
  for "not found": zero is a price.

## 4. Conditional formatting that cannot go stale

A painted fill is a second copy of a fact, and it goes stale the moment the number is edited.
Use rules.

- **Per-row baseline** (what a colour scale cannot do — its end points come from the whole
  range): a formula rule with a relative row and absolute column, applied to the block:
  `AND(ISNUMBER(D2),N($N2)>0,D2<=$N2*(1-cfg_sat))`. Thresholds from defined names. Six graded
  rules with `stopIfTrue`, plus one non-stopping rule (bold border on `D2=MIN($D2:$M2)`) so
  both apply to the same cell.
- Rule fills need **`bgColor`** (set both `fgColor` and `bgColor`): Excel reads a conditional
  `dxf` solid fill from `bgColor`.
- **Graded colour scale with editable end points**: `ColorScaleRule(start_type="formula",
  start_value="-cfg_sat", mid_type="num", mid_value=0, end_type="formula",
  end_value="cfg_sat")` — a defined name works as a cfvo formula, so the scale follows
  Settings.
- **On a PivotTable** (COM): `DataBodyRange.FormatConditions.AddColorScale(3)` then
  `ScopeType = 2` (`xlDataFieldScope`) so the scale follows the pivot as it is rearranged
  rather than being tied to the cells it happened to cover.
- Direction must be stated in the file (Notes + a legend on Settings): here red = the market is
  *cheaper* than the baseline.

## 5. PivotTables through COM

Driven from PowerShell (`research/excel/pivots.ps1`); Python only launches it.

- **Every COM call retries on `0x800AC472` ("busy")** (plus `RPC_E_*`, `0x8001010A`): Excel
  answers that intermittently while it is calculating or refreshing, and one unwrapped call
  fails the whole build. Any other error is raised with the step's name.
- Calculate first (`CalculateFull`, wait for `CalculationState = 0`): a pivot built over
  unevaluated formulas is empty.
- Source = the Table by name: `PivotCaches().Create(1, "tblOffers")` (`xlDatabase`). Create
  **one cache** and several pivots from it: slicers connect to pivots on the same cache, so
  one slicer drives them all (`SlicerCaches.Add2(pt, "Field")`, then
  `.PivotTables.AddPivotTable(other)`).
- Number formats on the **data field** (`DataField.NumberFormat`), not painted on cells.
- **Captions follow the Excel UI language** — a Russian Excel prints "Названия строк" and
  "Общий итог". Set `CompactLayoutRowHeader`, `CompactLayoutColumnHeader` and
  `GrandTotalName` so the workbook reads the same everywhere. Field names are the Table's own
  headers and are unaffected.
- Slicers: place them right of *both* the pivot and the chart below it; a pivot narrows after
  its captions are shortened, so compute the position after formatting.
- Pivot chart: legend at the bottom, `ShowAllFieldButtons = $false` (the slicers filter).
- **Optional steps never abort the build**: wrap style, colour scale, chart in a `Try-Step`
  that prints `WARN` and goes on; wrap required steps so a failure names the step.
- Always `Quit()` and release the COM object in `finally`, or a hidden `EXCEL.EXE` stays alive
  holding the file.

### Data Model (Power Pivot), probed

```
$wb.Model                                   # null / absent without Power Pivot → fall back to flat pivots
$wb.Connections.Add2("WorksheetConnection_tblX", "", "WORKSHEET;$file", "tblX", 7, $true, $false)
                                            # 7 = xlCmdExcel, True = add to the Data Model
$m.ModelRelationships.Add($fkColumn, $pkColumn)
$m.ModelMeasures.Add("Name", $table, "DAX…", $m.ModelFormatDecimalNumber(1,0), "description")
$pc = $wb.PivotCaches().Create(2, $wb.Connections.Item("ThisWorkbookDataModel"))
$pt.CubeFields.Item("[tblMarkets].[Market]").Orientation = 1
$pt.CubeFields.Item("[Measures].[Avg delta]").Orientation = 4
```

Do it in a `try`, and keep the flat pivots regardless: the flat tier is the guaranteed one.

## 6. PivotTables with no Excel (raw OOXML)

`research/excel/ooxml_pivot.py` writes the parts into the package and marks the cache
`refreshOnLoad="1"`, so Excel builds the pivots on first open (the same approach libraries
like EPPlus use). It needs: `pivotCacheDefinition` (source `<worksheetSource name="tblOffers"/>`,
one `cacheField` per Table column with empty `sharedItems`), an empty `pivotCacheRecords`
part, one `pivotTableDefinition` per pivot (axis fields carry just `<item t="default"/>`;
`rowFields`/`colFields`/`dataFields` declared; no `rowItems`/`colItems`), the relationships,
`[Content_Types].xml` overrides, and `<pivotCaches>` in `workbook.xml` after `<calcPr>`.

The first attempt (building the objects with `openpyxl.pivot`) produced a file Excel would not
open. The hand-written version failed the same way once, for a reason worth keeping: openpyxl's
`workbook.xml` declares `xmlns:r` only on each `<sheet>` element, so a bare
`<pivotCache r:id="…">` used an **undeclared prefix** and the package was invalid. Declare the
namespace on the element. Excel gives no diagnostic through COM — bisect by removing parts.

Limits: no slicers, no pivot chart, no Data Model, built-in number formats only
(`numFmtId` 3 = `#,##0`, 10 = `0.00%`).

## 7. Prove it in Excel, not in Python

openpyxl cannot evaluate a formula, so only Excel can say the file is valid.
`research/excel/verify.ps1`:

- opens, `CalculateFull`, then `UsedRange.SpecialCells(xlCellTypeFormulas, xlErrors)` per
  sheet — counts and names the first error cells;
- reports `ListObjects`, `PivotTables`, `SlicerCaches`, `FormatConditions` counts;
- `-Probe "Prices!D2,…"` returns each cell's **displayed** text and
  `DisplayFormat.Interior.Color` — the colour a conditional-format rule actually produces;
- `-Save` bakes the values in.

Then **recompute independently** in Python from the Offers rows and compare (grid, medians,
baselines, deltas, bands, per-market stats). Then **look**: `Worksheet.ExportAsFixedFormat`
to PDF, render with PyMuPDF, read the PNG — that is how an overlapping chart, an invisible
axis and a localised caption were found. Finally test *behaviour*: change an input through
COM (`Range.Value2`), recalc, probe the colours again.

## 8. Traps, one line each

| Symptom | Cause |
|---|---|
| Excel: "cannot get Open property of Workbooks" | Table column names ≠ header text; or an undeclared XML namespace prefix; bisect by deleting parts |
| `#NAME?` in a formula that looks right | newer function without `_xlfn.` |
| Pivot sheet empty | built before `CalculateFull`; or `refreshOnLoad` pivot over uncalculated formulas |
| Slicers vanished | the file was re-saved through openpyxl |
| Bar chart has no axis labels | openpyxl ≥ 3.1 hides axes: `axis.delete = False` |
| Colour rule shows no fill | solid fill without `bgColor` in a conditional `dxf` |
| "Row Labels" / "Общий итог" in the pivot | caption follows Excel's UI language: set the captions |
| COM call fails intermittently | `0x800AC472`: retry wrapper |
| Hidden `EXCEL.EXE` left running | `Quit()` not in `finally` |
| Colours "wrong" after sorting | baked fills; use rules |
