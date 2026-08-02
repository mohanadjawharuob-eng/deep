#!/usr/bin/env bash
#
# Stop the backend.
#
#     bash stop.sh
#
# Ctrl-C in the start window stops the website, but the database and the API
# keep running in Docker — usually what you want, occasionally not.
#
# Your data is kept. This stops the containers; it deletes nothing.

set -euo pipefail
cd "$(dirname "$0")"

echo
echo "Stopping the backend. Your data is kept."
echo

docker compose down

echo
echo "Stopped. Run 'bash start.sh' when you want it back."
echo
