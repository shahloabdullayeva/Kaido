#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./venv/bin/gunicorn \
  --bind "${HOST:-127.0.0.1}:${PORT:-8790}" \
  --workers "${WORKERS:-3}" \
  --worker-class gthread --threads 4 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
