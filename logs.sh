#!/usr/bin/env bash
#
# What the platform said about itself.
#
#     bash logs.sh
#
# The macOS and Linux twin of "Show Log.cmd". When something will not start,
# Docker's own message is always the same unhelpful sentence: "container
# archeo-api is unhealthy". That is a symptom. The reason is in the container's
# log, and this prints it — and writes it to stratum-log.txt so it can be
# attached to a message rather than retyped.
#
# It changes nothing. It only reads and prints.

set -uo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'
BOLD=$'\033[1m'; OFF=$'\033[0m'

echo
echo "${BOLD}Stratum — log${OFF}"
echo

[ -f docker-compose.yml ] || { echo "${RED}This does not look like the project folder.${OFF}"; exit 1; }

if ! docker info >/dev/null 2>&1; then
    echo "${YELLOW}Docker is not running, so there is no log to read.${OFF}"
    echo "${YELLOW}Start Docker, then try the platform again.${OFF}"
    exit 1
fi

# Both compose files, so this reads the same containers whether the platform
# was started with start.sh or share.sh. Compose ignores services from the
# override file that are not running.
COMPOSE=(-f docker-compose.yml)
[ -f docker-compose.prod.yml ] && COMPOSE+=(-f docker-compose.prod.yml)

OUT="$ROOT/stratum-log.txt"

# Deliberately no .env in here, at all. That file holds the database password,
# the signing key and — if it has been set up — the mail password, and a log
# people are encouraged to send on is the last place any of them should be.
{
    echo "Stratum log — $(date '+%Y-%m-%d %H:%M:%S')"
    echo
    echo "WHAT IS RUNNING"
    echo "-------------------------------------------------------"
    docker compose "${COMPOSE[@]}" ps --format "table {{.Name}}\t{{.Status}}" 2>&1
    echo

    # The database and the web server rarely fail in an interesting way. The
    # backend runs the migrations and reads the settings, so it is where a
    # wrong value in .env or a half-applied schema turns into an error.
    for service in api db web; do
        echo "THE $(echo "$service" | tr '[:lower:]' '[:upper:]') LOG"
        echo "-------------------------------------------------------"
        output="$(docker compose "${COMPOSE[@]}" logs --tail 80 --no-color "$service" 2>&1)"
        if [ -z "$output" ]; then
            echo "(nothing — this one has not run)"
        else
            echo "$output"
        fi
        echo
    done
} | tee "$OUT"

cat <<EOF

${BOLD}-------------------------------------------------------${OFF}
  The same text is saved here:
      ${GREEN}${OUT}${OFF}

  It contains no passwords — the settings file is not
  read by this at all — so it is safe to send on.
${BOLD}-------------------------------------------------------${OFF}

The lines that matter are usually the last few of the api
log, and anything with ERROR or Traceback in it.

EOF
