#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
{ echo "--- $(date -Is) ---"; ./venv/bin/python manage.py encourage 2>&1 | grep -v " INFO "; } >> "${LOG:-/root/kaido/encourage.log}"
