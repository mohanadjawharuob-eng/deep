#!/usr/bin/env bash
#
# Start the whole platform: Docker, the backend, the website, the browser.
#
#     bash start.sh
#
# The macOS and Linux twin of "Start Stratum.cmd". Same order, same checks:
#
#   1. Checks the settings file exists.
#   2. Starts Docker if it is not already running, and waits for it.
#   3. Fetches any new version of the project (skipped if you have edits).
#   4. Builds and starts the backend, and waits until it actually answers.
#   5. Starts the website and opens it.
#
# Ctrl-C stops the website. The backend keeps running in Docker; `bash stop.sh`
# shuts that down.

set -euo pipefail

cd "$(dirname "$0")"
ROOT="$PWD"

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'
BOLD=$'\033[1m'; OFF=$'\033[0m'

say()  { echo "${*}"; }
ok()   { echo "${GREEN}${*}${OFF}"; }
warn() { echo "${YELLOW}${*}${OFF}"; }
fail() { echo; echo "${RED}${*}${OFF}"; echo; exit 1; }

# Which compose files to use.
#
# docker-compose.storage.yml puts the uploaded photographs and the backups in a
# folder you choose rather than inside Docker's own area. It is opt-in, and the
# way you opt in is by setting DATA_ROOT in .env — which is no use at all if the
# launcher never passes the file.
#
# Read from .env rather than from the environment: a variable set in .env is not
# set in this shell. Compose reads that file itself, but by then it is too late
# to decide which files Compose should be reading.
compose_files() {
    local files=()
    local name
    for name in "$@"; do files+=(-f "$name"); done

    if [ -f .env ]; then
        local value
        value="$(sed -n 's/^[[:space:]]*DATA_ROOT[[:space:]]*=[[:space:]]*//p' .env | head -n1 | tr -d '"'"'"'\r')"
        if [ -n "$value" ]; then
            files+=(-f docker-compose.storage.yml)
            # To stderr: stdout is the list of arguments the caller reads back.
            echo "Files and backups go to $value" >&2
            # Docker will create a missing folder, but as root, and then it
            # cannot be opened without a fight. Better to make it here.
            [ -d "$value" ] || mkdir -p "$value" 2>/dev/null \
                || echo "  That folder does not exist and could not be created." >&2
        fi
    fi
    printf '%s\n' "${files[@]}"
}

# The backend's own log, when it is the backend that went wrong.
#
# Docker Compose only ever says the container is unhealthy, which is a symptom
# and never a reason. The reason is always in the container's log, and telling
# somebody to go and run `docker compose logs api` themselves is asking them to
# learn Docker in the middle of a problem. So print it here.
show_api_log() {
    echo
    echo "${YELLOW}What the backend itself said:${OFF}"
    echo "${YELLOW}-------------------------------------------------------${OFF}"
    docker compose "${COMPOSE[@]}" logs --tail 60 --no-color api 2>&1 || echo "(could not read the log)"
    echo "${YELLOW}-------------------------------------------------------${OFF}"
    echo
    echo "The last few lines are the ones that matter. If it is not obvious,"
    echo "copy them out and send them on — that block is enough to say"
    echo "exactly what went wrong."
}

fail_with_log() { echo; echo "${RED}${*}${OFF}"; show_api_log; echo; exit 1; }

echo
echo "${BOLD}Stratum${OFF}"
echo "Archaeological research and collections platform"
echo

# --------------------------------------------------------------------------
# 1. Settings
# --------------------------------------------------------------------------
[ -f docker-compose.yml ] || fail "This does not look like the project folder."

# Decided once, used by every command below — including the one that prints the
# log when something fails, which has to read the same containers that were
# started or it reports on nothing.
mapfile -t COMPOSE < <(compose_files docker-compose.yml)

if [ ! -f .env ]; then
    fail "No settings file yet. Run 'bash setup.sh' first — it creates .env and shows you the password to sign in with."
fi

# --------------------------------------------------------------------------
# 2. Docker
# --------------------------------------------------------------------------
command -v docker >/dev/null 2>&1 || fail \
    "Docker is not installed. Get Docker Desktop from https://www.docker.com/products/docker-desktop/"

# `docker info` is the honest test: the Desktop app can be open while its
# engine is still starting, and a compose command sent in that window fails
# with a confusing socket error rather than "please wait".
if docker info >/dev/null 2>&1; then
    ok "Docker is running."
else
    warn "Starting Docker..."
    if [ "$(uname)" = "Darwin" ]; then
        open -a Docker 2>/dev/null || warn "  Could not start Docker Desktop. Open it yourself."
    else
        warn "  Start Docker yourself (systemctl --user start docker-desktop, or open Docker Desktop)."
    fi

    # Generous rather than optimistic: a cold start on a slow laptop is
    # minutes, and a launcher that gives up early just gets run twice.
    deadline=$(( $(date +%s) + 180 ))
    until docker info >/dev/null 2>&1; do
        if [ "$(date +%s)" -gt "$deadline" ]; then
            fail "Docker did not finish starting within three minutes. Open it, wait for it to settle, and try again."
        fi
        printf "\r  waiting for the Docker engine... %ss" "$(( $(date +%s) - deadline + 180 ))"
        sleep 3
    done
    printf "\r                                          \r"
    ok "Docker is running."
fi

# --------------------------------------------------------------------------
# 3. Newer version, if there is one
# --------------------------------------------------------------------------
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
    # Never overwrite work in progress. Somebody who has edited a file wants
    # to know about it, not to have a launcher quietly clobber it.
    # Tracked changes only: an untracked file cannot be overwritten by a pull.
    if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
        warn "You have unsaved changes in the project folder, so it was not updated."
    else
        branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
        if [ -n "$branch" ]; then
            say "Checking for a newer version..."
            if git pull origin "$branch" --quiet >/dev/null 2>&1; then
                ok "Up to date."
            else
                warn "Could not check for updates (no internet?). Carrying on with what you have."
            fi
        fi
    fi
fi

# --------------------------------------------------------------------------
# 4. The backend
# --------------------------------------------------------------------------
echo
echo "${BOLD}Starting the backend. The first run after an update takes a few minutes.${OFF}"

# --build every time. Rebuilding is nearly instant when nothing has changed —
# Docker reuses its cached layers — and skipping it is the single most common
# way to end up running last week's code against this week's database.
docker compose "${COMPOSE[@]}" up --build -d || fail_with_log "The backend did not start."

# Up is not the same as ready: the container still has migrations to run.
say "Waiting for the backend to be ready..."
deadline=$(( $(date +%s) + 180 ))
until curl -fsS http://localhost:8000/api/v1/health >/dev/null 2>&1; do
    if [ "$(date +%s)" -gt "$deadline" ]; then
        fail_with_log "The backend started but never answered."
    fi
    sleep 2
done
ok "Backend ready."

# --------------------------------------------------------------------------
# 5. The website
# --------------------------------------------------------------------------
command -v npm >/dev/null 2>&1 || fail \
    "Node.js is not installed. Get the LTS version from https://nodejs.org/"

cd "$ROOT/frontend"

if [ ! -d node_modules ]; then
    echo
    echo "${BOLD}Installing the website's parts. This happens once and takes a minute.${OFF}"
    npm install
fi

echo
ok "Opening http://localhost:5173"
echo
echo "${BOLD}Leave this window open while you use the platform.${OFF}"
echo "Ctrl-C stops the website. To stop the backend too, run 'bash stop.sh'."
echo

# Give Vite a moment to bind the port before the browser asks for it,
# otherwise the first load is a connection error to refresh past.
(
    sleep 4
    if [ "$(uname)" = "Darwin" ]; then open http://localhost:5173 2>/dev/null || true
    else xdg-open http://localhost:5173 >/dev/null 2>&1 || true
    fi
) &

npm run dev
