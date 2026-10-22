<#
  Add real PivotTables, slicers and a pivot chart to a research workbook through Excel COM.

      powershell -NoProfile -ExecutionPolicy Bypass -File pivots.ps1 -Path book.xlsx [-Out out.xlsx] [-Model auto|yes|no]

  Input is a workbook written by narxnoma.research.workbook (Excel Tables tblOffers / tblProducts /
  tblMarkets). Output lines: PIVOT, SLICER, CHART, MODEL, WARN, RESULT.

  Three flat PivotTables read `tblOffers` through ONE shared pivot cache (so one slicer drives all
  three):
      Pivot by category       Category x Market   average delta vs baseline, colour scale, + pivot chart
      Pivot price matrix      Product  x Market   cheapest price
      Pivot market bands      Market   x Band     number of offers per heat band
  Slicers: Category, Market, Band.

  Data Model (Power Pivot): with -Model auto the script PROBES whether the Excel here has it. If yes it
  loads the three tables, relates Offers[Product] -> Products[Product] and Offers[Market] ->
  Markets[Market], adds DAX measures and one model-based PivotTable. If not (or on any failure) it
  prints "MODEL unavailable: <reason>" and the workbook keeps the three flat pivots -- the flat tables
  are the fallback, nothing is lost. -Model yes fails loudly instead of falling back; -Model no skips it.

  The same hard-won rules as the BI cube tooling: every COM call retries on 0x800AC472 ("busy");
  number formats are set on the data field, not painted on cells; optional steps never abort the build.
  Re-saving the result through openpyxl would silently drop the slicers: do not.
#>
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [string]$Out = "",
  [ValidateSet("auto", "yes", "no")][string]$Model = "auto"
)
$ErrorActionPreference = 'Stop'

function Invoke-Com([scriptblock]$Block, [string]$What) {
  for ($attempt = 1; $attempt -le 30; $attempt++) {
    try { return & $Block } catch {
      if ($_.Exception.Message -notmatch '800AC472|RPC_E_|0x8001010A') { throw "$What : $($_.Exception.Message)" }
      Start-Sleep -Milliseconds 400
    }
  }
  throw "Excel is not responding: $What"
}
function Try-Step([string]$What, [scriptblock]$Block) {
  try { Invoke-Com $Block $What | Out-Null } catch { Write-Output "WARN $What not done: $($_.Exception.Message)" }
}

$file = (Resolve-Path -LiteralPath $Path).Path
$target = if ($Out) { $Out } else { $file }
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false
try {
  $wb = Invoke-Com { $xl.Workbooks.Open($file) } "open"
  Invoke-Com { $xl.CalculateFull() } "calculate" | Out-Null          # the pivot must see values, not unevaluated formulas
  for ($w = 0; $w -lt 120; $w++) { if ((Invoke-Com { $xl.CalculationState } "state") -eq 0) { break }; Start-Sleep -Milliseconds 300 }

  function New-Sheet([string]$name, [string]$title, [string]$note) {
    $s = Invoke-Com { $wb.Worksheets.Add() } "sheet $name"
    Invoke-Com { $s.Name = $name } "name $name" | Out-Null
    Invoke-Com { $s.Move($wb.Worksheets.Item("Offers")) } "move $name" | Out-Null      # pivots sit before the data sheets
    Invoke-Com { $s.Range("A1").Value2 = $title; $s.Range("A1").Font.Bold = $true; $s.Range("A1").Font.Size = 14 } "title" | Out-Null
    Invoke-Com { $s.Range("A2").Value2 = $note; $s.Range("A2").Font.Italic = $true; $s.Range("A2").Font.Color = 8421504 } "note" | Out-Null
    return $s
  }
  function Finish-Pivot($pt, [string]$rowLabel = "", [string]$colLabel = "") {
    # Header and grand-total captions otherwise follow the Excel UI language ("Row Labels", "Grand Total",
    # "Названия строк"...): the same workbook would read differently on every machine.
    if ($rowLabel) { Try-Step "row header caption" { $pt.CompactLayoutRowHeader = $rowLabel } }
    if ($colLabel) { Try-Step "column header caption" { $pt.CompactLayoutColumnHeader = $colLabel } }
    Try-Step "grand total caption" { $pt.GrandTotalName = "Total" }
    Try-Step "pivot style" { $pt.TableStyle2 = "PivotStyleMedium2"; $pt.ShowTableStyleRowStripes = $true }
    Try-Step "keep column widths" { $pt.HasAutoFormat = $false }
    Try-Step "preserve formatting" { $pt.PreserveFormatting = $true }
  }

  $pc = Invoke-Com { $wb.PivotCaches().Create(1, "tblOffers") } "pivot cache"          # 1 = xlDatabase
  Try-Step "refresh on open" { $pc.RefreshOnFileOpen = $true }
  $pivots = @()

  # ---- 1: Category x Market, average delta vs baseline ----
  $ws1 = New-Sheet "Pivot by category" "Average market price vs baseline, by category and market" `
        "Negative (red) = the market is cheaper than your baseline. Slicers on the right filter all three pivot sheets. Data > Refresh All after edits."
  $pt1 = Invoke-Com { $pc.CreatePivotTable($ws1.Range("A5"), "pvtCategoryMarket") } "pivot 1"
  Invoke-Com { $pt1.PivotFields("Category").Orientation = 1 } "rows" | Out-Null
  Invoke-Com { $pt1.PivotFields("Market").Orientation = 2 } "columns" | Out-Null
  $df = Invoke-Com { $pt1.AddDataField($pt1.PivotFields("Delta vs baseline"), "Avg delta vs baseline", -4106) } "data field"   # xlAverage
  Invoke-Com { $df.NumberFormat = "+0.0%;-0.0%;0.0%" } "format" | Out-Null
  Finish-Pivot $pt1 "Category" "Market"
  Try-Step "colour scale on the pivot" {
    $cs = $pt1.DataBodyRange.FormatConditions.AddColorScale(3)
    $cs.ScopeType = 2                                                  # xlDataFieldScope: the scale follows the pivot as it changes
    $cs.ColorScaleCriteria.Item(1).Type = 0; $cs.ColorScaleCriteria.Item(1).Value = -0.2; $cs.ColorScaleCriteria.Item(1).FormatColor.Color = 7039480    # F8696B
    $cs.ColorScaleCriteria.Item(2).Type = 0; $cs.ColorScaleCriteria.Item(2).Value = 0;    $cs.ColorScaleCriteria.Item(2).FormatColor.Color = 16777215
    $cs.ColorScaleCriteria.Item(3).Type = 0; $cs.ColorScaleCriteria.Item(3).Value = 0.2;  $cs.ColorScaleCriteria.Item(3).FormatColor.Color = 8109667    # 63BE7B
  }
  $pivots += $pt1
  Write-Output "PIVOT pvtCategoryMarket on '$($ws1.Name)' $($pt1.TableRange1.Address($false,$false))"

  # ---- 2: Product x Market, cheapest price ----
  $ws2 = New-Sheet "Pivot price matrix" "Cheapest price by product and market" "The same numbers as Prices, as a pivot: drag Category / Band / Availability into rows, columns or filters."
  $pt2 = Invoke-Com { $pc.CreatePivotTable($ws2.Range("A5"), "pvtPriceMatrix") } "pivot 2"
  Invoke-Com { $pt2.PivotFields("Product").Orientation = 1 } "rows" | Out-Null
  Invoke-Com { $pt2.PivotFields("Market").Orientation = 2 } "columns" | Out-Null
  $df2 = Invoke-Com { $pt2.AddDataField($pt2.PivotFields("Price"), "Cheapest price", -4139) } "data field"                              # xlMin
  Invoke-Com { $df2.NumberFormat = "#,##0" } "format" | Out-Null
  Finish-Pivot $pt2 "Product" "Market"
  $pivots += $pt2
  Write-Output "PIVOT pvtPriceMatrix on '$($ws2.Name)' $($pt2.TableRange1.Address($false,$false))"

  # ---- 3: Market x Band, offer counts ----
  $ws3 = New-Sheet "Pivot market bands" "Offers per heat band, by market" "How many offers sit in each band against your baseline (band edges: Settings)."
  $pt3 = Invoke-Com { $pc.CreatePivotTable($ws3.Range("A5"), "pvtMarketBands") } "pivot 3"
  Invoke-Com { $pt3.PivotFields("Market").Orientation = 1 } "rows" | Out-Null
  Invoke-Com { $pt3.PivotFields("Band").Orientation = 2 } "columns" | Out-Null
  $df3 = Invoke-Com { $pt3.AddDataField($pt3.PivotFields("Product"), "Offers", -4112) } "data field"                                  # xlCount
  Invoke-Com { $df3.NumberFormat = "#,##0" } "format" | Out-Null
  Finish-Pivot $pt3 "Market" "Band"
  $pivots += $pt3
  Write-Output "PIVOT pvtMarketBands on '$($ws3.Name)' $($pt3.TableRange1.Address($false,$false))"

  # ---- slicers: one cache, so each slicer drives every pivot ----
  foreach ($f in @("Category", "Market", "Band")) {
    Try-Step "slicer $f" {
      $sc = $wb.SlicerCaches.Add2($pt1, $f)
      for ($k = 1; $k -lt $pivots.Count; $k++) { $sc.PivotTables.AddPivotTable($pivots[$k]) }
      # right of the pivot AND of the chart below it (the chart is 620 pt wide, starting at 10)
      $left = [Math]::Max($pt1.TableRange1.Left + $pt1.TableRange1.Width + 25, 10 + 620 + 25)
      $top = 60 + ([array]::IndexOf(@("Category", "Market", "Band"), $f)) * 190
      [void]$sc.Slicers.Add($ws1, [Type]::Missing, "slc$f", $f, $top, $left, 170, 175)
    }
    Write-Output "SLICER $f"
  }

  # ---- pivot chart under pivot 1 ----
  Try-Step "pivot chart" {
    $shape = $ws1.Shapes.AddChart2(201, 51, 10, $pt1.TableRange1.Top + $pt1.TableRange1.Height + 25, 620, 300)
    $shape.Chart.SetSourceData($pt1.TableRange1)
    $shape.Chart.HasTitle = $true; $shape.Chart.ChartTitle.Text = "Average market price vs baseline"
    $shape.Chart.HasLegend = $true; $shape.Chart.Legend.Position = -4107              # xlLegendPositionBottom: one colour per market
    $shape.Chart.ShowAllFieldButtons = $false                                         # the slicers do the filtering
  }
  Write-Output "CHART on '$($ws1.Name)'"

  # ---- Data Model, probed ----
  $modelState = "skipped (-Model no)"
  if ($Model -ne "no") {
    try {
      $m = Invoke-Com { $wb.Model } "wb.Model"                       # property absent / null when Power Pivot is not part of this Excel
      if ($null -eq $m) { throw "workbook.Model is not available in this Excel" }
      foreach ($t in @("tblOffers", "tblProducts", "tblMarkets")) {
        $cn = "WorksheetConnection_$t"
        [void](Invoke-Com { $wb.Connections.Add2($cn, "", "WORKSHEET;$file", $t, 7, $true, $false) } "model table $t")   # 7 = xlCmdExcel, True = add to the Data Model
      }
      $tabs = @{}
      foreach ($mt in $m.ModelTables) { $tabs[$mt.Name] = $mt }
      $o = $tabs["tblOffers"]; $p = $tabs["tblProducts"]; $mk = $tabs["tblMarkets"]
      if (-not ($o -and $p -and $mk)) { throw "the three tables did not all reach the model (found: $($tabs.Keys -join ', '))" }
      function Col($tab, $name) { foreach ($c in $tab.ModelTableColumns) { if ($c.Name -eq $name) { return $c } }; throw "no column $name in $($tab.Name)" }
      [void]$m.ModelRelationships.Add((Col $o "Product"), (Col $p "Product"))
      [void]$m.ModelRelationships.Add((Col $o "Market"), (Col $mk "Market"))
      $pctFmt = $m.ModelFormatPercentageNumber(1)
      $numFmt = $m.ModelFormatDecimalNumber(1, 0)
      [void]$m.ModelMeasures.Add("Offers count", $o, "COUNTROWS(tblOffers)", $m.ModelFormatWholeNumber(1), "Number of offers")
      [void]$m.ModelMeasures.Add("Median price", $o, "MEDIAN(tblOffers[Price])", $m.ModelFormatDecimalNumber(1, 0), "Median offer price")
      [void]$m.ModelMeasures.Add("Cheapest price", $o, "MIN(tblOffers[Price])", $m.ModelFormatDecimalNumber(1, 0), "Lowest offer price")
      [void]$m.ModelMeasures.Add("Avg delta", $o, "AVERAGE(tblOffers[Delta vs baseline])", $pctFmt, "Average delta vs baseline")
      [void]$m.ModelMeasures.Add("Share cheaper than baseline", $o, "DIVIDE(CALCULATE(COUNTROWS(tblOffers), tblOffers[Delta vs baseline] < 0), COUNTROWS(tblOffers))", $pctFmt, "Share of offers cheaper than the baseline")
      $ws4 = New-Sheet "Pivot model (DAX)" "Data Model pivot: Markets table x DAX measures" "Offers, Products and Markets are related in the Data Model; the measures are DAX. Filter by a Products column to cross tables."
      $mcn = $wb.Connections.Item("ThisWorkbookDataModel")
      $pcm = Invoke-Com { $wb.PivotCaches().Create(2, $mcn) } "model cache"      # 2 = xlExternal
      $ptm = Invoke-Com { $pcm.CreatePivotTable($ws4.Range("A5"), "pvtModel") } "model pivot"
      Invoke-Com { $ptm.CubeFields.Item("[tblMarkets].[Market]").Orientation = 1 } "model rows" | Out-Null
      foreach ($ms in @("Offers count", "Cheapest price", "Median price", "Avg delta", "Share cheaper than baseline")) {
        Invoke-Com { $ptm.CubeFields.Item("[Measures].[$ms]").Orientation = 4 } "measure $ms" | Out-Null
      }
      Finish-Pivot $ptm "Market"
      $modelState = "ok (3 tables, 2 relationships, 5 DAX measures)"
    } catch {
      if ($Model -eq "yes") { throw }
      $modelState = "unavailable: $($_.Exception.Message)"
    }
  }
  Write-Output "MODEL $modelState"

  Try-Step "select first sheet" { $wb.Worksheets.Item("Start").Activate() }
  Invoke-Com { $xl.CalculateFull() } "final calculate" | Out-Null
  if ($Out) { Invoke-Com { $wb.SaveAs($target, 51) } "save as" | Out-Null } else { Invoke-Com { $wb.Save() } "save" | Out-Null }
  Invoke-Com { $wb.Close($false) } "close" | Out-Null
  Write-Output "RESULT ok $target"
} finally {
  try { $xl.Quit() } catch { }
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
}
