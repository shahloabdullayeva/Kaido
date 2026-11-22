#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="${LOG:-/root/kaido/logs/sync.log}"
{
  echo "--- $(date -Is) ---"
  ./venv/bin/python manage.py sync --all || echo "samsara sync failed"
  ./venv/bin/python manage.py horizon-sync --all
  ./venv/bin/python manage.py safety || echo "safety pull failed"
} >> "$LOG" 2>&1
