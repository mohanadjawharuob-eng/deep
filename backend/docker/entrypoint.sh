#!/usr/bin/env bash
#
# Container entrypoint: wait for PostgreSQL, apply migrations, seed, then hand
# over to the command in CMD.
#
# Migrations run here rather than in the application so that a rollout with
# several replicas converges on one schema before any of them serve traffic;
# Alembic takes a lock on its version table, so concurrent starts are safe.

set -euo pipefail

log() { printf '%s [entrypoint] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
WAIT_TIMEOUT="${DB_WAIT_TIMEOUT:-60}"

# --- Wait for the database ------------------------------------------------
log "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT} (timeout ${WAIT_TIMEOUT}s)"
deadline=$(( $(date +%s) + WAIT_TIMEOUT ))
until python - "$DB_HOST" "$DB_PORT" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
try:
    with socket.create_connection((host, port), timeout=3):
        pass
except OSError:
    sys.exit(1)
PY
do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        log "ERROR: PostgreSQL did not become reachable within ${WAIT_TIMEOUT}s"
        exit 1
    fi
    sleep 1
done
log "PostgreSQL is reachable"

# --- Migrations -----------------------------------------------------------
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    log "Applying database migrations"
    alembic upgrade head
    log "Migrations applied"
else
    log "RUN_MIGRATIONS is not 'true'; skipping migrations"
fi

# --- Seed -----------------------------------------------------------------
# Idempotent, so running it on every boot only ever fills in what is missing.
if [ "${RUN_SEED:-true}" = "true" ]; then
    log "Seeding reference data"
    if [ "${SEED_SAMPLE_DATA:-false}" = "true" ]; then
        python -m scripts.seed --with-samples
    else
        python -m scripts.seed
    fi
else
    log "RUN_SEED is not 'true'; skipping seed"
fi

log "Starting: $*"
exec "$@"
