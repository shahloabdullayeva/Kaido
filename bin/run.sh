#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./venv/bin/flask --app "app:create_app()" run --host "${HOST:-127.0.0.1}" --port "${PORT:-8790}" --debug
