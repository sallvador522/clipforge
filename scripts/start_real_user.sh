#!/usr/bin/env bash
# ClipForge real-user startup (macOS/Linux, bash).
#
# Starts the full local stack in REAL USER MODE (all four providers live):
#   1. FastAPI backend  (http://127.0.0.1:8000, binds loopback only)
#   2. Persistent Python worker
#   3. Next.js Studio   (http://localhost:3000)
#
# Makes NO Meta API requests at startup (only local /health polls). Each model
# runs only when you request it in the Studio.
#
# Usage (from the repository root, after scripts/setup_judge.sh (one-time install) and after
# pasting your own Meta API key into .env):
#   bash scripts/start_real_user.sh

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/apps/web"
VENV_PY="$ROOT/.venv/bin/python"
ENV_FILE="$ROOT/.env"
PROFILE_ENV="$ROOT/scripts/real-user.env"
LOG_DIR="$ROOT/storage/logs"
API_PORT=8000
WEB_PORT=3000
API_URL="http://localhost:$API_PORT"
STUDIO_URL="http://localhost:$WEB_PORT"

PIDS=""

cleanup() {
  echo ""
  echo "==> Stopping ClipForge stack"
  # shellcheck disable=SC2086
  for pid in $PIDS; do kill "$pid" 2>/dev/null || true; done
  rm -f "$PID_FILE"
  # A worker has no port: match it by command line (narrow pattern).
  pkill -f "dev_worker\.py" 2>/dev/null || true
  # The web server may be a child of npm: match by server signature too.
  pkill -f "next-server" 2>/dev/null || true
  sleep 2
  # Belt and braces: kill anything still listening on our ports.
  for port in $API_PORT $WEB_PORT; do
    if command -v lsof >/dev/null 2>&1; then
      for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true); do
        kill -9 "$pid" 2>/dev/null || true
      done
    fi
  done
  for port in $API_PORT $WEB_PORT; do
    if (echo >/dev/tcp/127.0.0.1/$port) >/dev/null 2>&1; then
      echo "  WARNING: port $port still occupied; stop the owning process manually."
    else
      echo "  Port $port free"
    fi
  done
}
trap cleanup EXIT INT TERM

port_free() {
  ! (echo >/dev/tcp/127.0.0.1/$1) >/dev/null 2>&1
}

dotenv_value() { # file, name — prints value or empty; never logs secrets elsewhere
  local file="$1" name="$2" line
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?$name[[:space:]]*=" "$file" 2>/dev/null | tail -n 1 || true)"
  line="${line#export }"; line="${line#$name=}"; line="${line#$name =}"
  line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
  printf '%s' "$line"
}

# --- 1. Preflight: Real-user profile ---
if [ ! -f "$PROFILE_ENV" ]; then echo "ERROR: Real-user profile missing: $PROFILE_ENV" >&2; exit 1; fi
set -a
# shellcheck disable=SC1090
. "$PROFILE_ENV"
set +a
export NEXT_PUBLIC_API_URL="$API_URL"

# --- 2. Preflight: credentials (presence only, value never printed) ---
API_KEY="${MODEL_API_KEY:-}"
if [ -z "$API_KEY" ] && [ -f "$ENV_FILE" ]; then
  API_KEY="$(dotenv_value "$ENV_FILE" MODEL_API_KEY)"
fi
if [ -z "$API_KEY" ]; then
  echo "ERROR: MODEL_API_KEY is not set. Paste your own Meta API key into .env on the MODEL_API_KEY= line, then retry. (Your key is never printed or committed.)" >&2
  exit 1
fi
echo "  MODEL_API_KEY present (value never printed)"

# --- 3. Preflight: installation ---
if [ ! -x "$VENV_PY" ]; then echo "ERROR: Python environment missing. Run scripts/setup_judge.sh first (one-time install)." >&2; exit 1; fi
if [ ! -d "$WEB/node_modules" ]; then echo "ERROR: Frontend dependencies missing. Run scripts/setup_judge.sh first (one-time install)." >&2; exit 1; fi

# --- 4. Preflight: ports + duplicate worker ---
if ! port_free "$API_PORT"; then echo "ERROR: port $API_PORT is already in use. Stop the other service (or a previous ClipForge run) and retry." >&2; exit 1; fi
if ! port_free "$WEB_PORT"; then echo "ERROR: port $WEB_PORT is already in use. Stop the other service (or a previous ClipForge run) and retry." >&2; exit 1; fi
if pgrep -f "dev_worker\.py" >/dev/null 2>&1; then echo "ERROR: a ClipForge worker is already running. Stop it before starting another one." >&2; exit 1; fi

mkdir -p "$LOG_DIR"
PID_FILE="$LOG_DIR/real-user.pids"

# --- 4b. Preflight: stale run ---
if [ -f "$PID_FILE" ]; then
  STALE=""
  while IFS= read -r pid || [ -n "$pid" ]; do
    if kill -0 "$pid" 2>/dev/null; then STALE="$STALE $pid"; fi
  done < "$PID_FILE"
  if [ -n "$STALE" ]; then
    echo "ERROR: a previous ClipForge run is still active (PIDs$STALE). Stop it first: bash scripts/stop_real_user.sh" >&2
    exit 1
  fi
  rm -f "$PID_FILE"
fi

echo ""
echo "  REAL USER MODE: live AI calls bill YOUR OWN Meta account and may incur charges."
echo "  SAM sends a temporary video-only copy to Meta (consent-gated, 1-hour expiry, deleted after)."
echo ""

# --- 5. Launch (all on 127.0.0.1 via the dev launchers) ---
echo "==> Starting FastAPI backend ($API_URL)"
"$VENV_PY" scripts/dev_api.py >"$LOG_DIR/real-user-api.log" 2>"$LOG_DIR/real-user-api.err.log" &
PIDS="$PIDS $!"
echo "==> Starting persistent worker"
"$VENV_PY" scripts/dev_worker.py >"$LOG_DIR/real-user-worker.log" 2>"$LOG_DIR/real-user-worker.err.log" &
PIDS="$PIDS $!"
echo "==> Starting Studio frontend ($STUDIO_URL)"
(cd "$WEB" && npm run dev >"$LOG_DIR/real-user-web.log" 2>"$LOG_DIR/real-user-web.err.log" &)
PIDS="$PIDS $!"
printf '%s\n' $PIDS > "$PID_FILE"

# --- 6. Local health gate (local /health only, no Meta calls) ---
echo "==> Waiting for local API health"
HEALTHY=0
for _ in $(seq 1 45); do
  sleep 2
  if curl -sf --max-time 5 "$API_URL/health" -o /tmp/clipforge-real-user-health.json 2>/dev/null; then HEALTHY=1; break; fi
done
if [ "$HEALTHY" -ne 1 ]; then echo "ERROR: API did not become healthy in time. See storage/logs/real-user-api*.log." >&2; exit 1; fi

MODES="$(python3 -c "import json; h=json.load(open('/tmp/clipforge-real-user-health.json')); print('/'.join([h.get('transcribe_mode','?'),h.get('director_mode','?'),h.get('segmentation_mode','?'),h.get('image_mode','?')]))")"
if [ "$MODES" != "live/live/live/live" ]; then
  echo "  WARNING: API reports provider modes $MODES. Expected live/live/live/live."
  echo "  Check that scripts/real-user.env was applied and restart."
else
  echo "  Provider modes: transcribe/director/segmentation/image = live/live/live/live"
fi
rm -f /tmp/clipforge-real-user-health.json
echo "  No live requests made at startup (local health check only)."

echo ""
echo "  ClipForge Studio is ready: $STUDIO_URL"
echo "  Logs: storage/logs/real-user-*.log | Press Ctrl+C to stop all three services."
echo ""

wait
