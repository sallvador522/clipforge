# ClipForge detached stack launcher (ADR-054 hardening).
#
# Kills any previous stack, then starts API + worker + Studio as fully
# detached processes (no parent console dependency) plus a watchdog that
# polls /health and restarts a dead API. Run once from any shell:
#   powershell -ExecutionPolicy Bypass -File .\scripts\start_detached.ps1
# Stop with: .\scripts\stop_detached.ps1
#
# Live modes come from `.env` (transcribe/director/chat live). This launcher
# always sets CLIPFORGE_DEV_ALLOW_LIVE=1 so dev_api/dev_worker honour them.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "apps\web"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "storage\logs"
$pidFile = Join-Path $logDir "detached.pids"

New-Item -ItemType Directory -Force $logDir | Out-Null

function Stop-OldStack {
    foreach ($pattern in @("dev_api\.py", "dev_worker\.py", "idea_worker_proc", "next-server", "watch_clipforge\.ps1")) {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match $pattern } |
            ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
    }
    foreach ($port in @(8000, 3000)) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } catch {} }
    }
    Start-Sleep -Seconds 2
}

Stop-OldStack

if (-not (Test-Path $venvPython)) { throw "Python environment missing at $venvPython." }
if (-not (Test-Path (Join-Path $web "node_modules"))) { throw "Frontend dependencies missing. Run npm ci in apps/web first." }
$nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $nodeExe) { throw "node not found on PATH." }

$env:CLIPFORGE_DEV_ALLOW_LIVE = "1"
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"

$api = Start-Process -FilePath $venvPython -ArgumentList "scripts/dev_api.py" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "detached-api.log") `
    -RedirectStandardError (Join-Path $logDir "detached-api.err.log")
$worker = Start-Process -FilePath $venvPython -ArgumentList "scripts/dev_worker.py" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "detached-worker.log") `
    -RedirectStandardError (Join-Path $logDir "detached-worker.err.log")
$npmCli = Join-Path (Split-Path $nodeExe -Parent) "node_modules\npm\bin\npm-cli.js"
$frontend = Start-Process -FilePath $nodeExe -ArgumentList "`"$npmCli`"", "run", "dev" `
    -WorkingDirectory $web -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "detached-web.log") `
    -RedirectStandardError (Join-Path $logDir "detached-web.err.log")

@{ api = $api.Id; worker = $worker.Id; web = $frontend.Id } |
    ConvertTo-Json -Compress | Set-Content $pidFile

$watchdog = Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-ExecutionPolicy Bypass -File `"$PSScriptRoot\watch_clipforge.ps1`"" `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "watchdog.log") `
    -RedirectStandardError (Join-Path $logDir "watchdog.err.log")

$pids = Get-Content $pidFile -Raw | ConvertFrom-Json
$pids | Add-Member -NotePropertyName watchdog -NotePropertyValue $watchdog.Id
$pids | ConvertTo-Json -Compress | Set-Content $pidFile

Write-Host "Detached stack launched (api=$($api.Id) worker=$($worker.Id) web=$($frontend.Id) watchdog=$($watchdog.Id))"
Write-Host "Waiting for API health..."
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    try {
        $h = Invoke-RestMethod -UseBasicParsing "http://localhost:8000/health" -TimeoutSec 5
        if ($h.status -eq "ok") {
            Write-Host "API healthy: chat_mode=$($h.chat_mode) live_chat=$($h.live_chat_available)"
            exit 0
        }
    } catch {}
}
throw "API did not become healthy. See storage/logs/detached-api*.log."
