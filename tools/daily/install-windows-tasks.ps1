# Registers the two daily jobs with Windows Task Scheduler. Run once, in PowerShell, from the
# repo root. The PC's clock must be on Tashkent time (UTC+5) for 03:00 / 09:00 to mean that.
#   .\tools\daily\install-windows-tasks.ps1 -Python "C:\Python313\python.exe"
param(
    [string]$Python = "python",
    [string]$EnvFile = "$env:USERPROFILE\.narxnoma-daily.env"
)
$crawler = Join-Path (Resolve-Path .) "narxnoma-crawler"
function Register($name, $job, $time) {
    $arg = "-m narxnoma.daily $job --env-file `"$EnvFile`""
    $action = New-ScheduledTaskAction -Execute $Python -Argument $arg -WorkingDirectory $crawler
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 5) `
        -MultipleInstances IgnoreNew -WakeToRun
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "registered $name at $time"
}
Register "narxnoma-refresh" "refresh" "03:00"
Register "narxnoma-report"  "report"  "09:00"
