#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="${LOG:-/root/kaido/sync.log}"
{
  echo "--- $(date -Is) ---"
  ./venv/bin/python manage.py sync --all
} >> "$LOG" 2>&1
