#!/usr/bin/env bash
#
# Serve the platform to everyone on the same network.
#
#     bash share.sh
#
# The macOS and Linux twin of "Share on WiFi.cmd". The difference from
# start.sh: that runs a development setup only this machine can reach. This
# builds the interface properly, serves it on the normal web port, and prints
# the address for other people to type.
#
# Nobody else installs anything. Everyone shares one database, so a record
# catalogued on one machine is on every other one the moment they refresh.

set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'
BOLD=$'\033[1m'; OFF=$'\033[0m'

fail() { echo; echo "${RED}${*}${OFF}"; echo; exit 1; }

echo
echo "${BOLD}Stratum — share on this network${OFF}"
echo

[ -f docker-compose.yml ] || fail "This does not look like the project folder."
[ -f .env ] || fail "No settings file yet. Run 'bash setup.sh' first."

# --------------------------------------------------------------------------
# This machine's address on the network
# --------------------------------------------------------------------------

# The address on the interface that carries the default route. A laptop
# usually also has virtual interfaces from Docker and VPNs whose addresses are
# real but reach nobody — handing one of those to a colleague produces a page
# that never loads and no clue why.
find_lan_address() {
    if [ "$(uname)" = "Darwin" ]; then
        local iface
        iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
        [ -n "$iface" ] && ipconfig getifaddr "$iface" 2>/dev/null && return 0
    else
        ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}'
    fi
}

IP="$(find_lan_address || true)"

if [ -z "${IP:-}" ]; then
    echo "${YELLOW}Could not work out this computer's address on the network.${OFF}"
    read -r -p "Type it here: " IP
    [ -n "$IP" ] || fail "No address given, so there is nothing to share."
fi

echo "${GREEN}This computer is $IP on the network.${OFF}"

# --------------------------------------------------------------------------
# Record it in the settings
# --------------------------------------------------------------------------

# The platform prints its own address into QR codes and e-mails, so it has to
# be told the one people actually type — not localhost, which would send
# somebody scanning a label to their own machine.
set_env() {
    local key="$1" value="$2"
    if grep -qE "^[[:space:]]*${key}[[:space:]]*=" .env; then
        # A temporary file, then a move: an interrupted in-place edit of the
        # file holding the database password is not a thing to risk.
        awk -v k="$key" -v v="$value" \
            'BEGIN{FS=OFS="="} $1 ~ "^[[:space:]]*"k"[[:space:]]*$" {print k"="v; next} {print}' \
            .env > .env.tmp && mv .env.tmp .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

# The router hands out addresses on a lease, so this machine's number can
# change after a reboot — and then every bookmark and every printed QR code
# points at nothing. The computer's *name* does not change, and Macs, iPhones
# and Androids all resolve the `.local` form on a local network. Using the
# name means an address change costs nobody anything, which is a better answer
# than restarting on a timer and hoping.
HOSTNAME_LOCAL="$(hostname -s 2>/dev/null || hostname).local"
NAME_URL="http://$HOSTNAME_LOCAL"

set_env SITE_ADDRESS ":80"
set_env PUBLIC_URL "$NAME_URL"

# --------------------------------------------------------------------------
# Docker
# --------------------------------------------------------------------------
command -v docker >/dev/null 2>&1 || fail "Docker is not installed."

if ! docker info >/dev/null 2>&1; then
    echo "${YELLOW}Starting Docker...${OFF}"
    [ "$(uname)" = "Darwin" ] && open -a Docker 2>/dev/null || true
    deadline=$(( $(date +%s) + 180 ))
    until docker info >/dev/null 2>&1; do
        [ "$(date +%s)" -gt "$deadline" ] && fail "Docker did not finish starting."
        sleep 3
    done
fi
echo "${GREEN}Docker is running.${OFF}"

# --------------------------------------------------------------------------
# Build and serve
# --------------------------------------------------------------------------
echo
echo "${BOLD}Building. The first time takes several minutes; after that it is quick.${OFF}"
echo

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build \
    || fail "It did not start. The messages above say why."

echo "Waiting for it to be ready..."
deadline=$(( $(date +%s) + 180 ))
until curl -fsS http://localhost/api/v1/health >/dev/null 2>&1; do
    [ "$(date +%s)" -gt "$deadline" ] && fail "It started but never answered. Run 'docker compose logs api'."
    sleep 2
done

cat <<EOF

${BOLD}-------------------------------------------------------${OFF}
  Anyone on this network can now open:

      ${GREEN}${NAME_URL}${OFF}

  or, if that does not work for them:
      http://$IP

${BOLD}-------------------------------------------------------${OFF}

Give out the first one. The number can change when the
router restarts; the name does not. That is why labels
and links use the name.

They install nothing. They just type that address.
Everyone shares one database, so a record added on one
machine appears on every other one when it refreshes.

${YELLOW}Give each person their own account rather than sharing
yours: the platform records who changed what, and that
is worth nothing if everybody is you.${OFF}

This computer must stay on and awake.

It keeps running after you close this window.
'bash stop.sh' shuts it down.

EOF
