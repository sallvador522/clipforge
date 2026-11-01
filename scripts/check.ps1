# ClipForge local verification.
# Runs backend tests, frontend typecheck and a production build.
# Usage (from the repository root):
#   .\scripts\check.ps1
# If PowerShell blocks the script:
#   powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "apps\web"
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    $python = "python"
}

if (-not (Test-Path (Join-Path $web "node_modules"))) {
    throw "Frontend dependencies are missing. Run 'npm ci' in apps/web first."
}

Push-Location $root
# PowerShell 5.1 promotes native stderr (e.g. FFmpeg's expected probe noise)
# to a terminating error when ErrorActionPreference is Stop. Keep it non-
# terminating for native commands and validate their real exit codes instead.
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    Write-Host "==> Backend tests (pytest)" -ForegroundColor Cyan
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Backend tests failed."
    }

    Push-Location $web
    try {
        Write-Host "==> Frontend typecheck" -ForegroundColor Cyan
        & npm run typecheck
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend typecheck failed."
        }

        Write-Host "==> Frontend production build" -ForegroundColor Cyan
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build failed."
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "All checks passed." -ForegroundColor Green
}
finally {
    $ErrorActionPreference = $previousErrorAction
    Pop-Location
}
