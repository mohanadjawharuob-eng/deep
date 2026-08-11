#!/usr/bin/env bash
# Take a backup of everything. The macOS and Linux twin of scripts/backup.ps1;
# the reasoning is written out there.
#
# Usage:  bash backup.sh [folder]
#
# With no folder it writes beside the project, which is better than nothing
# and worse than a second disk - so it says so.
set -euo pipefail

cd "$(dirname "$0")"

say() { printf '%s\n' "$1"; }

if ! command -v docker >/dev/null 2>&1; then
  say "Docker is not installed, so there is nothing to back up from."
  exit 1
fi

if ! docker compose ps --status running --services 2>/dev/null | grep -qx db; then
  say "The platform is not running, so the database cannot be read."
  say "Start it with 'bash start.sh', then run this again."
  exit 1
fi

stamp="$(date +%Y-%m-%d-%H%M)"
base="${1:-$PWD}"
target="$base/stratum-backup-$stamp"
mkdir -p "$target/files"

say ""
say "Backing up to $target"
say ""

say "1 of 3  The records..."
docker compose exec -T db pg_dump -U postgres -d archeo --clean --if-exists > "$target/records.sql"
if [ ! -s "$target/records.sql" ]; then
  say "The database dump came out empty, which means it did not work. Nothing else was written."
  exit 1
fi
say "        records.sql - $(du -h "$target/records.sql" | cut -f1)"

say "2 of 3  The photographs and documents..."
if docker compose cp "api:/data/uploads/." "$target/files" >/dev/null 2>&1; then
  say "        $(find "$target/files" -type f | wc -l | tr -d ' ') files - $(du -sh "$target/files" | cut -f1)"
else
  say "        Could not copy the files. The records were still saved."
fi

say "3 of 3  Writing the instructions..."
cat > "$target/RESTORE.txt" <<TXT
STRATUM BACKUP
Taken $(date '+%A %-d %B %Y, %H:%M')

WHAT IS IN HERE

  records.sql   Every record in the platform, as text.
  files/        Every photograph, document and 3D model.

PUTTING IT BACK

  1. Start Docker, then start only the database:

       docker compose up -d db

  2. Load the records back in. This REPLACES what is in the platform now:

       docker compose exec -T db psql -U postgres -d archeo < records.sql

  3. Put the files back:

       docker compose up -d api
       docker compose cp "files/." api:/data/uploads

  4. Start everything the normal way.

WHAT THIS DOES NOT INCLUDE

Your settings file (.env), which holds the database and e-mail passwords.
That is deliberate: it is a credential, and backups get carried about.
TXT

say ""
say "Done. The backup is at:"
say "  $target"
say ""
say "Worth doing: copy that folder somewhere that is not this building."
