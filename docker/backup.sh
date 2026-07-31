#!/usr/bin/env bash
#
# Periodic database backup.
#
# Dumps in PostgreSQL's custom format (``-Fc``): compressed, and restorable
# selectively with ``pg_restore``. Old dumps are pruned by age.
#
# Restore a dump with:
#     pg_restore --clean --if-exists -d "$PGDATABASE" /backups/<file>.dump

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

log() { printf '%s [backup] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

mkdir -p "$BACKUP_DIR"

log "Backup loop started: every ${INTERVAL}s, keeping ${RETENTION_DAYS} days in ${BACKUP_DIR}"

while true; do
    # Wait for the database before the first attempt, so a compose-wide
    # restart does not log a spurious failure.
    if ! pg_isready --quiet; then
        log "Database not ready; retrying in 30s"
        sleep 30
        continue
    fi

    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    target="${BACKUP_DIR}/${PGDATABASE}-${stamp}.dump"

    # Dump to a temporary name and rename on success, so a partial file is
    # never mistaken for a usable backup.
    if pg_dump --format=custom --compress=6 --file="${target}.partial"; then
        mv "${target}.partial" "$target"
        log "Wrote $(basename "$target") ($(du -h "$target" | cut -f1))"
    else
        rm -f "${target}.partial"
        log "ERROR: pg_dump failed; no backup written this cycle"
    fi

    deleted=$(find "$BACKUP_DIR" -name '*.dump' -type f -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)
    if [ "$deleted" -gt 0 ]; then
        log "Pruned ${deleted} dump(s) older than ${RETENTION_DAYS} days"
    fi

    sleep "$INTERVAL"
done
