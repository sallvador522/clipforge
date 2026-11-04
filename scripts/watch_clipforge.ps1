# ClipForge watchdog (ADR-054 hardening).
#
# Started detached by scripts/start_detached.ps1. Polls /health every 20 s:
# after 3 consecutive failures it restarts the API; dead worker/web/console
# processes in detached.pids are restarted too. Restart storms are capped
# (max 6 API restarts per rolling hour) so a broken deploy fails loudly in
# storage/logs/watchdog.log instead of churning. Stop with
# scripts/stop_detached.ps1.

$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "apps\web"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "storage\logs"
$pidFile = Join-Path $logDir "detached.pids"

function Write-WatchdogLog([string]$message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
    Add-Content (Join-Path $logDir "watchdog.log") $line
    Write-Output $line
}

function Read-Pids {
    try { return (Get-Content $pidFile -Raw -ErrorAction Stop | ConvertFrom-Json) }
    catch { return $null }
}

function Write-Pids($pids) {
    $pids | ConvertTo-Json -Compress | Set-Content $pidFile
}

function Test-ProcessAlive($id) {
    if (-not $id) { return $false }
    try { Get-Process -Id ([int]$id) -ErrorAction Stop | Out-Null; return $true }
    catch { return $false }
}

function Start-Api {
    $env:CLIPFORGE_DEV_ALLOW_LIVE = "1"
    $env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
    foreach ($port in @(8000)) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } catch {} }
    }
    Start-Sleep -Seconds 2
    $p = Start-Process -FilePath $venvPython -ArgumentList "scripts/dev_api.py" `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "detached-api.log") `
        -RedirectStandardError (Join-Path $logDir "detached-api.err.log")
    return $p.Id
}

function Start-Worker {
    $env:CLIPFORGE_DEV_ALLOW_LIVE = "1"
    $p = Start-Process -FilePath $venvPython -ArgumentList "scripts/dev_worker.py" `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "detached-worker.log") `
        -RedirectStandardError (Join-Path $logDir "detached-worker.err.log")
    return $p.Id
}

function Start-Web {
    $env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
    $nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
    if (-not $nodeExe) { Write-WatchdogLog "web restart skipped: node not found"; return $null }
    $npmCli = Join-Path (Split-Path $nodeExe -Parent) "node_modules\npm\bin\npm-cli.js"
    $p = Start-Process -FilePath $nodeExe -ArgumentList "`"$npmCli`"", "run", "dev" `
        -WorkingDirectory $web -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "detached-web.log") `
        -RedirectStandardError (Join-Path $logDir "detached-web.err.log")
    return $p.Id
}

$failures = 0
$apiRestarts = @()
Write-WatchdogLog "watchdog started (pid $PID)"

while ($true) {
    Start-Sleep -Seconds 20
    $healthy = $false
    try {
        $h = Invoke-RestMethod -UseBasicParsing "http://localhost:8000/health" -TimeoutSec 8
        if ($h.status -eq "ok") { $healthy = $true }
    } catch {}
    if ($healthy) {
        $failures = 0
    } else {
        $failures++
        Write-WatchdogLog "health check failed ($failures/3)"
    }

    $pids = Read-Pids
    if (-not (Test-ProcessAlive $pids.worker)) {
        Write-WatchdogLog "worker dead; restarting"
        $newId = Start-Worker
        if ($pids) { $pids.worker = $newId; Write-Pids $pids }
    }
    if (-not (Test-ProcessAlive $pids.web)) {
        Write-WatchdogLog "web dead; restarting"
        $newId = Start-Web
        if ($pids -and $newId) { $pids.web = $newId; Write-Pids $pids }
    }

    if ($failures -ge 3) {
        $failures = 0
        $now = Get-Date
        $apiRestarts = @($apiRestarts | Where-Object { $_ -gt $now.AddHours(-1) })
        if ($apiRestarts.Count -ge 6) {
            Write-WatchdogLog "GIVING UP: 6 API restarts in the last hour; leaving stack as-is"
            exit 1
        }
        $apiRestarts += $now
        Write-WatchdogLog "api unhealthy 3x; restarting (restart #$($apiRestarts.Count) in the last hour)"
        try {
            $newId = Start-Api
            $pids = Read-Pids
            if ($pids) { $pids.api = $newId; Write-Pids $pids }
            Write-WatchdogLog "api restarted (pid $newId)"
        } catch {
            Write-WatchdogLog "api restart failed: $($_.Exception.Message)"
        }
    }
}
