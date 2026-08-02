#!/usr/bin/env bash
#
# Lift the four offline apps out of this project and into a folder of their
# own, ready to push to their own repository.
#
#     bash scripts/extract-apps.sh
#
# They were never part of the archaeology platform — nothing in it imports
# them, links to them, or serves them. They are four self-contained web pages
# that happened to share a folder. This moves them out with their history
# intact, so `git log` in the new repository still says who changed what and
# why.
#
# You can run this whether or not the `apps/` folder is still in the current
# checkout: the extraction reads git history, not the working tree, and the
# history keeps the folder for good.

set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'
BOLD=$'\033[1m'; OFF=$'\033[0m'

fail() { echo; echo "${RED}${*}${OFF}"; echo; exit 1; }

# The last commit that had `apps/` in it. Pinned rather than discovered,
# because after the folder is removed there is nothing left in HEAD to
# discover it from — and a script that works today and not next month is
# worse than no script.
SOURCE_COMMIT="fa8e2739e51a6df65610697fd137e009faa29d9b"
DESTINATION="${1:-../offline-apps}"

command -v git >/dev/null 2>&1 || fail "Git is not installed."
git rev-parse --git-dir >/dev/null 2>&1 || fail "This is not a git checkout."

if ! git cat-file -e "${SOURCE_COMMIT}^{commit}" 2>/dev/null; then
    fail "This checkout does not have the commit the apps were last in.
Run 'git fetch --all' and try again."
fi

if [ -e "$DESTINATION" ]; then
    fail "$DESTINATION already exists. Move it aside, or pass another path:
    bash scripts/extract-apps.sh ../somewhere-else"
fi

echo
echo "${BOLD}Extracting the four offline apps${OFF}"
echo

# `subtree split` rewrites the folder's commits so its contents sit at the
# root — which is what they need to be in a repository of their own.
#
# It has to be run somewhere the folder actually exists on disk: given only a
# commit it still refuses with "'apps' does not exist", which is why this
# checks out that commit into a scratch worktree first rather than pointing
# the split at it directly. The split writes into the shared object store, so
# the branch it makes is visible back here afterwards.
echo "Reading their history..."
BRANCH="apps-extract-$$"
WORKTREE="$(mktemp -d)/apps-source"

cleanup() {
    git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
    git branch -D "$BRANCH" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git worktree add -q --detach "$WORKTREE" "$SOURCE_COMMIT" \
    || fail "Could not open the commit the apps were last in."

git -C "$WORKTREE" subtree split --prefix=apps --branch "$BRANCH" >/dev/null 2>&1 \
    || fail "Could not read the apps' history."

COUNT="$(git rev-list --count "$BRANCH")"
echo "${GREEN}Found $COUNT commits.${OFF}"

# A fresh repository, with only those commits in it.
git init -q "$DESTINATION"
git -C "$DESTINATION" fetch -q "$PWD" "$BRANCH"
git -C "$DESTINATION" checkout -q -b main FETCH_HEAD

FULL="$(cd "$DESTINATION" && pwd)"

cat <<EOF

${BOLD}-------------------------------------------------------${OFF}
  Done. The apps are now at:

      ${GREEN}${FULL}${OFF}

  with all $COUNT of their commits.

${BOLD}-------------------------------------------------------${OFF}

${BOLD}What to do next${OFF}

1. Go to https://github.com/new
2. Name it            ${GREEN}offline-apps${OFF}
3. Leave it ${BOLD}Private${OFF} unless you want the world to see it.
4. Do ${BOLD}not${OFF} tick "Add a README" — the folder already has files,
   and an extra one only causes a conflict.
5. Press ${BOLD}Create repository${OFF}.
6. Then paste these two lines, one at a time:

    cd "$FULL"
    git remote add origin https://github.com/${GITHUB_USER:-YOUR-USERNAME}/offline-apps.git
    git push -u origin main

That is the whole migration. The apps keep their history; this project
stops carrying four pages that were never part of it.

${YELLOW}Nothing is lost either way.${OFF} Even after the folder is removed from
this project, it stays in this project's history, and running this
script again brings it back.

EOF
