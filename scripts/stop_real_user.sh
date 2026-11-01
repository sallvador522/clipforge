#!/usr/bin/env bash
# ClipForge real-user stop script (macOS/Linux, bash).
#
# Stops a real-user stack even if its startup terminal was closed: reads
# storage/logs/real-user.pids, kills those processes, then kills anything still
# listening on ports 8000/3000 and any stray ClipForge worker.
#
# Usage (from the repository root):
#   bash scripts/stop_real_user.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/storage/logs/real-user.pids"

if [ -f "$PID_FILE" ]; then
  while IFS= read -r pid || [ -n "$pid" ]; do
    kill "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  rm -f "$PID_FILE"
  echo "  Stopped PIDs from real-user.pids"
else
  echo "  No real-user.pids found (stack may already be stopped)"
fi

pkill -f "dev_worker\.py" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true

for port in 8000 3000; do
  if command -v lsof >/dev/null 2>&1; then
    for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true); do
      kill -9 "$pid" 2>/dev/null || true
    done
  fi
done

sleep 2
CLEAN=1
for port in 8000 3000; do
  if (echo >/dev/tcp/127.0.0.1/$port) >/dev/null 2>&1; then
    echo "  WARNING: port $port still occupied; stop the owning process manually."
    CLEAN=0
  else
    echo "  Port $port free"
  fi
done
if [ "$CLEAN" -eq 1 ]; then echo "ClipForge stack stopped."; fi
