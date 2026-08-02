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

# Stop with a heading somebody can find.
#
# Everything that goes wrong in here ends the same way from outside: Docker
# says "container archeo-api is unhealthy" and the launcher closes. Whoever is
# reading the log afterwards is scrolling through several hundred lines of
# start-up chatter looking for the one that matters, so it is worth making that
# line impossible to miss, and worth saying what to do about it.
die() {
    printf '\n'
    printf '=======================================================\n'
    printf ' STRATUM DID NOT START\n'
    printf '=======================================================\n'
    printf '%s\n' "$1"
    if [ -n "${2:-}" ]; then
        printf '\n%s\n' "$2"
    fi
    printf '=======================================================\n\n'
    exit 1
}

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
        die "The database never answered on ${DB_HOST}:${DB_PORT} within ${WAIT_TIMEOUT} seconds." \
"The database container is called archeo-db. Its own log will say
whether it failed to start or is simply slow on this machine.

If it is only slow, raise DB_WAIT_TIMEOUT in .env and try again."
    fi
    sleep 1
done
log "PostgreSQL is reachable"

# --- Settings -------------------------------------------------------------
# Checked on its own, before anything uses them. Every step below imports the
# settings, so one bad value in .env otherwise surfaces as a wall of Pydantic
# traceback in the middle of "applying migrations" — which reads like the
# migrations are broken when the real problem is a typo two files away.
if ! settings_error="$(python -c 'from app.core.config import settings; settings.mail_configured' 2>&1)"; then
    die "One of the settings in .env is not valid, so nothing else could start." \
"$settings_error"
fi

# --- Migrations -----------------------------------------------------------
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    log "Applying database migrations"
    if ! alembic upgrade head; then
        die "The database could not be brought up to date. The Alembic output above says where it stopped." \
"Nothing has been half-applied — a migration that fails is rolled
back — so the database is as it was before this attempt.

The usual causes:
  * The database already holds a newer version of the schema than
    this copy of the code knows about. Update the project.
  * A migration was interrupted previously and its lock is still
    held. Restarting the database container clears it."
    fi
    log "Migrations applied"
else
    log "RUN_MIGRATIONS is not 'true'; skipping migrations"
fi

# --- Seed -----------------------------------------------------------------
# Idempotent, so running it on every boot only ever fills in what is missing.
if [ "${RUN_SEED:-true}" = "true" ]; then
    log "Seeding reference data"
    if [ "${SEED_SAMPLE_DATA:-false}" = "true" ]; then
        seed_args=(--with-samples)
    else
        seed_args=()
    fi
    if ! python -m scripts.seed "${seed_args[@]}"; then
        die "The reference data could not be written. The output above says why." \
"This step creates the first administrator account and the
standard vocabularies. It is safe to run again once the cause
is fixed — it only ever fills in what is missing."
    fi
else
    log "RUN_SEED is not 'true'; skipping seed"
fi

log "Starting: $*"
exec "$@"
