#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec 8>/tmp/kaido-brand-prices.lock
flock -n 8 || exit 0
{ echo "--- $(date -Is) ---"; ./venv/bin/python manage.py brand-prices; ./venv/bin/python manage.py eia-prices; } >> /root/kaido/logs/brand-prices.log 2>&1
