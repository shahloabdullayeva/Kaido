#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec 9>/tmp/kaido-followup.lock
flock -n 9 || exit 0
LOG="${LOG:-/root/kaido/followup.log}"
OUT=$(./venv/bin/python manage.py followup 2>&1) || true
if [ -n "$OUT" ]; then
  { echo "--- $(date -Is) ---"; echo "$OUT"; } >> "$LOG"
fi
