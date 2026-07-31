#!/usr/bin/env bash
#
# First-time setup for macOS and Linux.
#
#     bash setup.sh
#
# Creates the .env file the platform needs, with strong random values filled in
# for you, and prints the password you will sign in with. Safe to read before
# running: it writes exactly one file (.env) in this folder and nothing else.

set -euo pipefail

cd "$(dirname "$0")"

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'

echo
echo "${BOLD}Archaeological Research Platform — setup${OFF}"
echo "----------------------------------------"
echo

if [ ! -f .env.example ]; then
    echo "Could not find .env.example. Run this from inside the project folder."
    exit 1
fi

if [ -f .env ]; then
    echo "${YELLOW}A .env file already exists.${OFF}"
    printf "Replace it with fresh settings? Your current passwords will be lost. [y/N] "
    read -r reply
    case "$reply" in
        [yY]*) ;;
        *) echo "Left your existing .env alone. Nothing changed."; exit 0 ;;
    esac
fi

# --- Generate the values -------------------------------------------------
# openssl ships with macOS and virtually every Linux; the /dev/urandom branch
# is the fallback for a stripped-down system.
random_string() {
    local length="$1"
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 "$((length * 2))" | tr -d '/+=\n' | cut -c1-"$length"
    else
        LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$length"
    fi
}

SECRET_KEY="$(random_string 64)"
DB_PASSWORD="$(random_string 24)"
# Built to satisfy the password policy by construction — at least ten
# characters with an upper case letter, a lower case letter and a digit — so
# setup cannot fail on a rule the person running it never saw.
ADMIN_PASSWORD="Dig$(random_string 12)7x"

# --- Write .env ----------------------------------------------------------
cp .env.example .env

replace() {
    # A portable in-place edit: BSD sed (macOS) and GNU sed (Linux) disagree
    # about -i, so write to a temporary file and move it into place.
    local key="$1" value="$2"
    awk -v k="$key" -v v="$value" \
        'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' .env > .env.tmp
    mv .env.tmp .env
}

replace SECRET_KEY "$SECRET_KEY"
replace POSTGRES_PASSWORD "$DB_PASSWORD"
replace FIRST_ADMIN_PASSWORD "$ADMIN_PASSWORD"
replace SEED_SAMPLE_DATA true

chmod 600 .env  # passwords: readable only by you

# --- Tell the user what happens next -------------------------------------
echo "${GREEN}✓ Settings created.${OFF}"
echo
echo "${BOLD}Write these down — you need them to sign in:${OFF}"
echo
echo "    Address:   http://localhost:8000/docs"
echo "    E-mail:    admin@example.org"
echo "    Password:  ${BOLD}${ADMIN_PASSWORD}${OFF}"
echo
echo "(They are also saved in the .env file in this folder.)"
echo
echo "${BOLD}Next step — start the platform:${OFF}"
echo
echo "    docker compose up --build"
echo
echo "The first run takes a few minutes while it downloads and builds."
echo "It is ready when you see a line containing 'Application startup complete'."
echo
