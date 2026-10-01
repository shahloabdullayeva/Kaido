#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${DEST:-/root/backups/fleet}"
mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M)
DB_URL=$(grep '^DATABASE_URL=' .env | cut -d= -f2-)
pg_dump --enable-row-security "$DB_URL" | gzip > "$DEST/fleet-$STAMP.sql.gz"
find "$DEST" -name 'fleet-*.sql.gz' -mtime +14 -delete
echo "backup written to $DEST/fleet-$STAMP.sql.gz"
./venv/bin/python manage.py pti-cleanup
