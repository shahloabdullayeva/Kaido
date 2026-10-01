#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${DEST:-/root/backups/fleet}"
mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M)
DB_URL=$(grep '^DATABASE_URL=' .env | cut -d= -f2-)
pg_dump --enable-row-security "$DB_URL" | gzip > "$DEST/fleet-$STAMP.sql.gz"
./venv/bin/python manage.py pti-cleanup
mkdir -p uploads
tar -czf "$DEST/uploads-$STAMP.tar.gz" uploads
find "$DEST" \( -name 'fleet-*.sql.gz' -o -name 'uploads-*.tar.gz' \) -mtime +28 -delete
echo "backup written to $DEST/fleet-$STAMP.sql.gz and $DEST/uploads-$STAMP.tar.gz"
./venv/bin/python manage.py summary --backup "$DEST/fleet-$STAMP.sql.gz" "$DEST/uploads-$STAMP.tar.gz"
