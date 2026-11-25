#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="${LOG:-/root/kaido/logs/sync.log}"
exec 9>/tmp/kaido-sync.lock
flock -n 9 || exit 0
{
  echo "--- $(date -Is) ---"
  ./venv/bin/python manage.py sync --all || echo "samsara sync failed"
  if [ "${1:-}" = "--with-horizon" ] || [ $(( 10#$(date +%M) % 15 )) -lt 5 ]; then
    ./venv/bin/python manage.py horizon-sync --all
    ./venv/bin/python manage.py weather || echo "weather failed"
  fi
  ./venv/bin/python manage.py safety || echo "safety pull failed"
} >> "$LOG" 2>&1
