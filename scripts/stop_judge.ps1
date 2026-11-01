# ClipForge judge stop script (Windows PowerShell).
#
# Stops a judge stack even if its startup terminal was closed: reads
# storage/logs/judge.pids, kills those processes, then kills anything still
# listening on ports 8000/3000 and any stray ClipForge worker.
#
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\stop_judge.ps1

$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "storage\logs\judge.pids"

if (Test-Path $pidFile) {
    foreach ($id in (Get-Content $pidFile)) {
        try { Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue } catch {}
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "  Stopped PIDs from judge.pids"
} else {
    Write-Host "  No judge.pids found (stack may already be stopped)"
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "dev_worker\.py|next-server" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }

foreach ($port in @(8000, 3000)) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        try { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } catch {}
    }
}

Start-Sleep -Seconds 2
$leftover = $false
foreach ($port in @(8000, 3000)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "  WARNING: port $port still occupied; stop the owning process manually." -ForegroundColor Yellow
        $leftover = $true
    } else {
        Write-Host "  Port $port free" -ForegroundColor Green
    }
}
if (-not $leftover) { Write-Host "ClipForge stack stopped." -ForegroundColor Green }
