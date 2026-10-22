<#
  Open a research workbook in real Excel, recalculate it, and report what Excel itself sees.

      powershell -NoProfile -ExecutionPolicy Bypass -File verify.ps1 -Path book.xlsx [-Save] [-Probe "Prices!D2,Prices!E2"]

  Why this exists: openpyxl writes formulas but cannot evaluate them, so a typo (#NAME?, #REF!, a
  function that needs a newer Excel) is invisible until a person opens the file. This is the same
  trick as recalculating through COM in the BI cube tooling: let Excel do it and read back.

  Reports, one line each:  OPEN, ERRORS (count + first cells per sheet), TABLES, PIVOTS, SLICERS,
  CF (conditional-format rules per sheet), PROBE (value and fill colour of the cells you name).
  -Save writes the recalculated values back, so viewers that do not calculate (previews, pandas)
  see numbers instead of blanks. Never run this against a workbook a person has open.

  Excel automation sometimes answers 0x800AC472 ("busy"); every call retries.
#>
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [switch]$Save,
  [string]$Probe = ""
)
$ErrorActionPreference = 'Stop'

function Invoke-Com([scriptblock]$Block, [string]$What) {
  for ($attempt = 1; $attempt -le 25; $attempt++) {
    try { return & $Block } catch {
      if ($_.Exception.Message -notmatch '800AC472|RPC_E_|0x8001010A') { throw "$What : $($_.Exception.Message)" }
      Start-Sleep -Milliseconds 400
    }
  }
  throw "Excel is not responding: $What"
}

$file = (Resolve-Path -LiteralPath $Path).Path
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false
try {
  $wb = Invoke-Com { $xl.Workbooks.Open($file) } "open"
  Invoke-Com { $xl.CalculateFull() } "calculate" | Out-Null
  for ($w = 0; $w -lt 120; $w++) { if ((Invoke-Com { $xl.CalculationState } "state") -eq 0) { break }; Start-Sleep -Milliseconds 300 }
  "OPEN  $($wb.Name)  Excel $($xl.Version)  sheets=$($wb.Worksheets.Count)"
  $totalErr = 0
  foreach ($ws in $wb.Worksheets) {
    $errs = 0; $first = @()
    try {
      $cells = Invoke-Com { $ws.UsedRange.SpecialCells(-4123, 16) } "errors in $($ws.Name)"   # xlCellTypeFormulas, xlErrors
      foreach ($c in $cells.Cells) { $errs++; if ($first.Count -lt 3) { $first += "$($c.Address($false,$false))=$($c.Text)" } }
    } catch { }                                                                                # no matching cells -> exception
    $totalErr += $errs
    $cf = Invoke-Com { $ws.Cells.FormatConditions.Count } "cf count"
    $lo = Invoke-Com { $ws.ListObjects.Count } "tables"
    $pv = Invoke-Com { $ws.PivotTables().Count } "pivots"
    "SHEET $($ws.Name): errors=$errs $($first -join ' ') | tables=$lo pivots=$pv cf_rules=$cf"
  }
  $slicers = 0
  try { $slicers = $wb.SlicerCaches.Count } catch { }
  "SLICERS $slicers"
  "ERRORS_TOTAL $totalErr"
  if ($Probe) {
    foreach ($ref in $Probe.Split(",")) {
      $sheet, $addr = $ref.Trim().Split("!")
      $c = Invoke-Com { $wb.Worksheets.Item($sheet).Range($addr) } "probe $ref"
      $rgb = Invoke-Com { $c.DisplayFormat.Interior.Color } "colour $ref"
      $hex = "{0:X2}{1:X2}{2:X2}" -f ($rgb -band 255), (($rgb -shr 8) -band 255), (($rgb -shr 16) -band 255)
      "PROBE $ref text=[$($c.Text)] fill=$hex bold=$($c.DisplayFormat.Font.Bold)"
    }
  }
  if ($Save) { Invoke-Com { $wb.Save() } "save" | Out-Null; "SAVED" }
  Invoke-Com { $wb.Close($false) } "close" | Out-Null
} finally {
  try { $xl.Quit() } catch { }
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
}
