#!/usr/bin/env bash
# ClipForge judge setup (macOS/Linux, bash).
#
# Installs local dependencies and prepares `.env` from the template.
# Idempotent: existing installs and an existing `.env` are never overwritten.
# Makes NO Meta API requests (only pip + npm).
#
# Usage (from the repository root):
#   bash scripts/setup_judge.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/apps/web"
VENV_PY="$ROOT/.venv/bin/python"
ENV_FILE="$ROOT/.env"
ENV_EXAMPLE="$ROOT/.env.example"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: $1 not found on PATH. $2" >&2
    exit 1
  fi
}

echo "==> Checking required tools"
need python3 "Install Python 3.11+ from https://www.python.org/downloads/ and retry."
PYV="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PYV%%.*}"; PY_MINOR="${PYV#*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  echo "ERROR: Python 3.11+ is required (found $PYV)." >&2
  exit 1
fi
echo "  python OK ($PYV)"
need node "Install Node.js 20+ from https://nodejs.org/ and retry."
need npm "npm ships with Node.js 20+."
NODE_MAJOR="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "ERROR: Node.js 20+ is required (found $(node --version))." >&2
  exit 1
fi
echo "  node OK ($(node --version)), npm OK ($(npm --version))"
need ffmpeg "Install FFmpeg (macOS: 'brew install ffmpeg'; Ubuntu: 'sudo apt install ffmpeg') and retry."
need ffprobe "ffprobe ships with FFmpeg."
echo "  ffmpeg/ffprobe OK"

if [ ! -x "$VENV_PY" ]; then
  echo "==> Creating Python virtual environment (.venv)"
  python3 -m venv "$ROOT/.venv"
else
  echo "  .venv already exists, keeping it"
fi

if ! "$VENV_PY" -c "import clipforge_api, clipforge_worker, fastapi, uvicorn, cv2" >/dev/null 2>&1; then
  echo "==> Installing Python dependencies (pip only, no Meta calls)"
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -e "$ROOT[dev,api,worker]"
else
  echo "  Python dependencies already installed, skipping"
fi

if [ ! -d "$WEB/node_modules" ]; then
  echo "==> Installing frontend dependencies (npm ci, no Meta calls)"
  (cd "$WEB" && npm ci)
else
  echo "  apps/web/node_modules already present, skipping"
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "==> Creating .env from .env.example (no secrets inside)"
  cp "$ENV_EXAMPLE" "$ENV_FILE"
else
  echo "  .env already exists, keeping it (not overwritten)"
fi

KEY_PRESENT=0
while IFS= read -r raw || [ -n "$raw" ]; do
  line="$(echo "$raw" | sed -e 's/^[[:space:]]*//' -e 's/^export //')"
  case "$line" in
    MODEL_API_KEY=*)
      value="$(echo "${line#MODEL_API_KEY=}" | sed -e 's/^[[:space:]]*//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
      if [ -n "$value" ]; then KEY_PRESENT=1; fi
      ;;
  esac
done < "$ENV_FILE"

if [ "$KEY_PRESENT" -eq 1 ]; then
  echo "  MODEL_API_KEY is set in .env (value never printed)"
else
  echo ""
  echo "  ACTION NEEDED: paste your own Meta API key into .env on the MODEL_API_KEY= line,"
  echo "  then run scripts/start_judge.sh. See docs/JUDGE_QUICKSTART.md."
fi

echo ""
echo "Setup complete. Start ClipForge with: bash scripts/start_judge.sh"
