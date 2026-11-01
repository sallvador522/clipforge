# ClipForge judge setup (Windows PowerShell).
#
# Installs local dependencies and prepares `.env` from the template.
# Idempotent: existing installs and an existing `.env` are never overwritten.
# Makes NO Meta API requests (only pip + npm).
#
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_judge.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "apps\web"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$envFile = Join-Path $root ".env"
$envExample = Join-Path $root ".env.example"

function Test-CommandOnPath($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Get-VersionTuple($text) {
    if ($text -match "(\d+)\.(\d+)") {
        return @([int]$Matches[1], [int]$Matches[2])
    }
    return @()
}

Write-Host "==> Checking required tools" -ForegroundColor Cyan

# --- Python 3.11+ ---
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw "Python not found on PATH. Install Python 3.11+ from https://www.python.org/downloads/ and retry." }
$pyVersion = Get-VersionTuple(& python --version 2>&1)
if ($pyVersion.Count -lt 2 -or $pyVersion[0] -lt 3 -or ($pyVersion[0] -eq 3 -and $pyVersion[1] -lt 11)) {
    throw "Python 3.11+ is required (found: $(& python --version 2>&1))."
}
Write-Host "  python OK ($( & python --version 2>&1 ))" -ForegroundColor Green

# --- Node.js 20+ ---
if (-not (Test-CommandOnPath "node")) { throw "Node.js not found on PATH. Install Node.js 20+ from https://nodejs.org/ and retry." }
if (-not (Test-CommandOnPath "npm")) { throw "npm not found on PATH. It ships with Node.js 20+." }
$nodeVersion = Get-VersionTuple(& node --version 2>&1)
if ($nodeVersion.Count -lt 2 -or $nodeVersion[0] -lt 20) {
    throw "Node.js 20+ is required (found: $(& node --version 2>&1))."
}
Write-Host "  node OK ($( & node --version 2>&1 )), npm OK ($( & npm --version 2>&1 ))" -ForegroundColor Green

# --- FFmpeg + ffprobe ---
if (-not (Test-CommandOnPath "ffmpeg")) { throw "ffmpeg not found on PATH. Install it (Windows: 'winget install Gyan.FFmpeg') and retry." }
if (-not (Test-CommandOnPath "ffprobe")) { throw "ffprobe not found on PATH. It ships with FFmpeg." }
Write-Host "  ffmpeg/ffprobe OK" -ForegroundColor Green

# --- Python virtual environment ---
if (-not (Test-Path $venvPython)) {
    Write-Host "==> Creating Python virtual environment (.venv)" -ForegroundColor Cyan
    & python -m venv (Join-Path $root ".venv")
} else {
    Write-Host "  .venv already exists, keeping it" -ForegroundColor Green
}

# --- Python dependencies (skip when already installed) ---
$needInstall = $false
try {
    & $venvPython -c "import clipforge_api, clipforge_worker, fastapi, uvicorn, cv2" 2>$null
    if ($LASTEXITCODE -ne 0) { $needInstall = $true }
} catch {
    $needInstall = $true
}
if ($needInstall) {
    Write-Host "==> Installing Python dependencies (pip only, no Meta calls)" -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
    & $venvPython -m pip install -e "$root[dev,api,worker]"
    if ($LASTEXITCODE -ne 0) { throw "Python dependency install failed." }
} else {
    Write-Host "  Python dependencies already installed, skipping" -ForegroundColor Green
}

# --- Frontend dependencies (skip when already installed) ---
if (-not (Test-Path (Join-Path $web "node_modules"))) {
    Write-Host "==> Installing frontend dependencies (npm ci, no Meta calls)" -ForegroundColor Cyan
    Push-Location $web
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "  apps/web/node_modules already present, skipping" -ForegroundColor Green
}

# --- Local configuration (never overwrite, never print secrets) ---
if (-not (Test-Path $envFile)) {
    Write-Host "==> Creating .env from .env.example (no secrets inside)" -ForegroundColor Cyan
    Copy-Item $envExample $envFile
} else {
    Write-Host "  .env already exists, keeping it (not overwritten)" -ForegroundColor Green
}

$keyPresent = $false
foreach ($raw in (Get-Content $envFile)) {
    $line = $raw.Trim()
    if ($line.StartsWith("export ")) { $line = $line.Substring(7) }
    if ($line -match "^MODEL_API_KEY\s*=\s*(.+)\s*$") {
        $value = $Matches[1].Trim().Trim('"').Trim("'")
        if ($value -ne "") { $keyPresent = $true }
    }
}
if ($keyPresent) {
    Write-Host "  MODEL_API_KEY is set in .env (value never printed)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  ACTION NEEDED: paste your own Meta API key into .env on the MODEL_API_KEY= line," -ForegroundColor Yellow
    Write-Host "  then run scripts/start_judge.ps1. See docs/JUDGE_QUICKSTART.md." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete. Start ClipForge with: powershell -ExecutionPolicy Bypass -File .\scripts\start_judge.ps1" -ForegroundColor Green
