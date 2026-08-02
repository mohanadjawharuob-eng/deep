# Lift the four offline apps out of this project and into a folder of their own.
#
# Do not run this directly — double-click "Extract Apps.cmd" instead.
#
# They were never part of the archaeology platform: nothing in it imports them,
# links to them, or serves them. This moves them out with their history intact,
# so `git log` in the new repository still says who changed what and why.

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

function Say([string]$Text, [string]$Colour = "Gray") { Write-Host $Text -ForegroundColor $Colour }

function Fail([string]$Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

# The last commit that had `apps/` in it. Pinned rather than discovered,
# because after the folder is removed there is nothing left in the current
# checkout to discover it from.
$SourceCommit = "fa8e2739e51a6df65610697fd137e009faa29d9b"

# Next to the project, not inside it — putting the extracted repository under
# a git checkout makes a nested repository, which git treats as an untracked
# blob and which confuses every tool that looks at either one.
$parent = Split-Path -Parent $Root
if ([string]::IsNullOrWhiteSpace($parent)) {
    # The project sits at a drive root, so there is no "next to it".
    $parent = $Root
}
$Destination = Join-Path $parent "offline-apps"

Write-Host ""
Say "Extracting the four offline apps" "White"
Write-Host ""

try { git --version | Out-Null } catch { Fail "Git is not installed." }

git rev-parse --git-dir 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "This is not a git checkout." }

git cat-file -e "$SourceCommit^{commit}" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "This checkout does not have the commit the apps were last in.`nRun 'git fetch --all' and try again."
}

if (Test-Path $Destination) {
    Fail "$Destination already exists. Move it aside and try again."
}

# `subtree split` has to be run somewhere the folder actually exists on disk:
# given only a commit it still refuses with "'apps' does not exist". So the
# commit is checked out into a scratch worktree first. The split writes into
# the shared object store, so the branch it makes is visible back here.
Say "Reading their history..."

$branch = "apps-extract-$PID"
$worktree = Join-Path ([System.IO.Path]::GetTempPath()) "apps-source-$PID"

try {
    git worktree add -q --detach $worktree $SourceCommit 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "Could not open the commit the apps were last in." }

    git -C $worktree subtree split --prefix=apps --branch $branch 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "Could not read the apps' history." }

    $count = (git rev-list --count $branch).Trim()
    Say "Found $count commits." "Green"

    git init -q $Destination
    git -C $Destination fetch -q "$Root" $branch
    git -C $Destination checkout -q -b main FETCH_HEAD
} finally {
    git worktree remove --force $worktree 2>&1 | Out-Null
    git branch -D $branch 2>&1 | Out-Null
}

$full = (Resolve-Path $Destination).Path

Write-Host ""
Say "-------------------------------------------------------" "White"
Say "  Done. The apps are now at:" "White"
Write-Host ""
Say "      $full" "Green"
Write-Host ""
Say "  with all $count of their commits."
Say "-------------------------------------------------------" "White"
Write-Host ""
Say "What to do next" "White"
Write-Host ""
Say "  1. Go to https://github.com/new"
Say "  2. Name it            offline-apps" "Green"
Say "  3. Leave it Private unless you want the world to see it."
Say "  4. Do NOT tick 'Add a README' — the folder already has files,"
Say "     and an extra one only causes a conflict."
Say "  5. Press Create repository."
Write-Host ""
Say "  6. Then paste these three lines, one at a time:"
Write-Host ""
Say "     cd `"$full`"" "Green"
Say "     git remote add origin https://github.com/YOUR-USERNAME/offline-apps.git" "Green"
Say "     git push -u origin main" "Green"
Write-Host ""
Say "Nothing is lost either way. Even with the folder gone from this" "Yellow"
Say "project, it stays in this project's history, and running this" "Yellow"
Say "again brings it back." "Yellow"
Write-Host ""

Start-Process $full
Read-Host "Press Enter to close this window"
