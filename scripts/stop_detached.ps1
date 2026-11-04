# Stop the detached ClipForge stack (see scripts/start_detached.ps1).
# Kills the watchdog first so it does not restart components mid-shutdown,
# then API/worker/web by pidfile, then any leftovers by port/command line.

$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "storage\logs"
$pidFile = Join-Path $logDir "detached.pids"

try { $pids = Get-Content $pidFile -Raw -ErrorAction Stop | ConvertFrom-Json }
catch { $pids = $null }

foreach ($name in @("watchdog", "api", "worker", "web")) {
    $id = if ($pids) { $pids.$name } else { $null }
    if ($id) {
        try { Stop-Process -Id ([int]$id) -Force -ErrorAction Stop; Write-Host "stopped $name ($id)" }
        catch { Write-Host "$name ($id) already gone" }
    }
}
Start-Sleep -Seconds 2
foreach ($pattern in @("watch_clipforge\.ps1", "dev_api\.py", "dev_worker\.py", "idea_worker_proc", "next-server")) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $pattern } |
        ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
}
foreach ($port in @(8000, 3000)) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } catch {} }
}
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "detached stack stopped"
exit 0
