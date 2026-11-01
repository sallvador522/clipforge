# ClipForge real-user startup (Windows PowerShell).
#
# Starts the full local stack in REAL USER MODE (all four providers live):
#   1. FastAPI backend  (http://127.0.0.1:8000, binds loopback only)
#   2. Persistent Python worker
#   3. Next.js Studio   (http://localhost:3000)
#
# Makes NO Meta API requests at startup (only local /health polls). Each model
# runs only when you request it in the Studio.
#
# Usage (from the repository root, after scripts/setup_judge.ps1 (one-time install) and after
# pasting your own Meta API key into .env):
#   powershell -ExecutionPolicy Bypass -File .\scripts\start_real_user.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "apps\web"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$envFile = Join-Path $root ".env"
$profileEnv = Join-Path $PSScriptRoot "real-user.env"
$logDir = Join-Path $root "storage\logs"
$apiPort = 8000
$webPort = 3000
$apiUrl = "http://localhost:$apiPort"
$studioUrl = "http://localhost:$webPort"

function Read-DotEnvValue($path, $name) {
    foreach ($raw in (Get-Content $path -ErrorAction SilentlyContinue)) {
        $line = $raw.Trim()
        if ($line.StartsWith("export ")) { $line = $line.Substring(7) }
        if ($line -match "^$name\s*=\s*(.*)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function Test-PortFree($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return ($null -eq $conn)
}

# --- 1. Preflight: Real-user profile ---
if (-not (Test-Path $profileEnv)) { throw "Real-user profile missing: $profileEnv" }
foreach ($raw in (Get-Content $profileEnv)) {
    $line = $raw.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { continue }
    $key, $value = $line.Split("=", 2)
    if ($key -and $value -ne $null) {
        [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), "Process")
    }
}
$env:NEXT_PUBLIC_API_URL = $apiUrl

# --- 2. Preflight: credentials (presence only, value never printed) ---
$apiKey = $env:MODEL_API_KEY
if ([string]::IsNullOrWhiteSpace($apiKey) -and (Test-Path $envFile)) {
    $apiKey = Read-DotEnvValue $envFile "MODEL_API_KEY"
}
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "MODEL_API_KEY is not set. Paste your own Meta API key into .env on the MODEL_API_KEY= line, then retry. (Your key is never printed or committed.)"
}
Write-Host "  MODEL_API_KEY present (value never printed)" -ForegroundColor Green

# --- 3. Preflight: installation ---
if (-not (Test-Path $venvPython)) {
    throw "Python environment missing. Run scripts/setup_judge.ps1 first (one-time install)."
}
if (-not (Test-Path (Join-Path $web "node_modules"))) {
    throw "Frontend dependencies missing. Run scripts/setup_judge.ps1 first (one-time install)."
}

# --- 4. Preflight: ports + duplicate worker ---
if (-not (Test-PortFree $apiPort)) {
    throw "Port $apiPort is already in use. Stop the other service (or a previous ClipForge run) and retry."
}
if (-not (Test-PortFree $webPort)) {
    throw "Port $webPort is already in use. Stop the other service (or a previous ClipForge run) and retry."
}
$existingWorker = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "dev_worker\.py" }
if ($existingWorker) {
    throw "A ClipForge worker is already running (PID $($existingWorker.ProcessId)). Stop it before starting another one."
}

New-Item -ItemType Directory -Force $logDir | Out-Null
$pidFile = Join-Path $logDir "real-user.pids"

# --- 4b. Preflight: stale run ---
if (Test-Path $pidFile) {
    $stale = @()
    foreach ($id in (Get-Content $pidFile)) {
        try { $p = Get-Process -Id ([int]$id) -ErrorAction Stop; $stale += $id } catch {}
    }
    if ($stale.Count -gt 0) {
        throw "A previous ClipForge run is still active (PIDs $($stale -join ', ')). Stop it first: scripts/stop_judge.ps1 or scripts/stop_real_user.ps1"
    }
    Remove-Item $pidFile -Force
}

Write-Host ""
Write-Host "  REAL USER MODE: live AI calls bill YOUR OWN Meta account and may incur charges." -ForegroundColor Yellow
Write-Host "  SAM sends a temporary video-only copy to Meta (consent-gated, 1-hour expiry, deleted after)." -ForegroundColor Yellow
Write-Host ""

# --- 5. Launch (all on 127.0.0.1 via the dev launchers) ---
$launched = @()
Write-Host "==> Starting FastAPI backend ($apiUrl)" -ForegroundColor Cyan
$api = Start-Process -FilePath $venvPython -ArgumentList "scripts/dev_api.py" `
    -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "real-user-api.log") `
    -RedirectStandardError (Join-Path $logDir "real-user-api.err.log")
$launched += $api.Id

Write-Host "==> Starting persistent worker" -ForegroundColor Cyan
$worker = Start-Process -FilePath $venvPython -ArgumentList "scripts/dev_worker.py" `
    -WorkingDirectory $root -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "real-user-worker.log") `
    -RedirectStandardError (Join-Path $logDir "real-user-worker.err.log")
$launched += $worker.Id

Write-Host "==> Starting Studio frontend ($studioUrl)" -ForegroundColor Cyan
$nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $nodeExe) { throw "node not found on PATH. Run scripts/setup_judge.ps1 first (one-time install)." }
# Run npm's CLI directly under node (no cmd.exe wrapper) so the process tree
# is killable on shutdown and no orphans remain.
$npmCli = Join-Path (Split-Path $nodeExe -Parent) "node_modules\npm\bin\npm-cli.js"
if (-not (Test-Path $npmCli)) { throw "npm CLI not found next to node at $nodeExe." }
$frontend = Start-Process -FilePath $nodeExe -ArgumentList "`"$npmCli`"", "run", "dev" `
    -WorkingDirectory $web -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "real-user-web.log") `
    -RedirectStandardError (Join-Path $logDir "real-user-web.err.log")
$launched += $frontend.Id
Set-Content $pidFile ($launched -join "`n")

function Stop-RealUserStack {
    foreach ($id in $launched) {
        try { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } catch {}
    }
    # Belt and braces: a second worker has no port, so match it by command line.
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "dev_worker\.py" } |
        ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
    # The web server may be a child of npm: match it by server signature too.
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "next-server" } |
        ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
    # And kill anything still listening on our ports so no orphans remain.
    foreach ($port in @($apiPort, $webPort)) {
        $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pid in $owner) {
            try { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}

# --- 6. Local health gate (local /health only, no Meta calls) ---
try {
    Write-Host "==> Waiting for local API health" -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds(90)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if ($api.HasExited) { throw "API exited during startup. See storage/logs/real-user-api*.log." }
        try {
            $health = Invoke-RestMethod -UseBasicParsing "$apiUrl/health" -TimeoutSec 5
            if ($health.status -eq "ok") { $healthy = $true; break }
        } catch {}
    }
    if (-not $healthy) { throw "API did not become healthy in time. See storage/logs/real-user-api*.log." }

    $liveModes = @($health.transcribe_mode, $health.director_mode, $health.segmentation_mode, $health.image_mode)
    if ($liveModes -contains "mock") {
        Write-Host "  WARNING: API reports a non-live provider mode ($($liveModes -join '/')). Expected live/live/live/live." -ForegroundColor Yellow
        Write-Host "  Check that scripts/real-user.env was applied and restart." -ForegroundColor Yellow
    } else {
        Write-Host "  Provider modes: transcribe/director/segmentation/image = live/live/live/live" -ForegroundColor Green
    }
    Write-Host "  Live-call usage: $(($health.live_calls_used | ConvertTo-Json -Compress)) (no requests made at startup)" -ForegroundColor Green

    Write-Host ""
    Write-Host "  ClipForge Studio is ready: $studioUrl" -ForegroundColor Green
    Write-Host "  Logs: storage/logs/real-user-*.log | Press Ctrl+C to stop all three services." -ForegroundColor Green
    Write-Host ""

    # Block until Ctrl+C; the finally clause always shuts the stack down.
    Wait-Process -Id $launched
}
finally {
    Write-Host ""
    Write-Host "==> Stopping ClipForge stack" -ForegroundColor Cyan
    Stop-RealUserStack
    Remove-Item (Join-Path $logDir "real-user.pids") -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    foreach ($port in @($apiPort, $webPort)) {
        if (Test-PortFree $port) {
            Write-Host "  Port $port free" -ForegroundColor Green
        } else {
            Write-Host "  WARNING: port $port still occupied; stop the owning process manually." -ForegroundColor Yellow
        }
    }
}
