# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# Fetch the newest version of the platform, and rebuild.
#
# "Start Stratum" already fetches quietly on its way past, which is right for
# the ordinary case and wrong for the case where somebody has been told a fix
# is waiting. This is that case: it says what it is doing, shows what changed,
# and stops with a reason rather than carrying on with the old code.
#
# Three things it will not do, all deliberate:
#
#   It will not touch your edits. If anything in the folder has been changed,
#   it stops and says so. A launcher that stashes or discards somebody's work
#   to save a step is a launcher nobody should trust with an archive.
#
#   It will not erase data. Updating rebuilds the program; the database and the
#   uploaded files are untouched, and a migration that needs to change the
#   database runs itself on the next start.
#
#   It will not start anything. Update, then press Start - so a failed update
#   is a failed update rather than a platform that will not open.

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

function Say([string]$Text, [string]$Colour = "Gray") {
    Write-Host $Text -ForegroundColor $Colour
}

function Stop-Here([string]$Text) {
    Write-Host ""
    Say $Text "Red"
    Write-Host ""
    Read-Host "Press Enter to close this window"
    exit 1
}

Write-Host ""
Say "Updating Stratum" "White"
Say "----------------" "White"
Write-Host ""

# --------------------------------------------------------------------------
# 1. Is there a way to update at all?
# --------------------------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Stop-Here @"
Git is not installed, so there is no way to fetch a newer version.

Install it from https://git-scm.com/download/win - the default answers to
every question are correct - then close this window and try again.
"@
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
    Stop-Here @"
This folder was copied rather than cloned, so there is nothing to update from.

Download the project again with Git, or ask for a fresh copy.
"@
}

# --------------------------------------------------------------------------
# 2. Your work comes first
# --------------------------------------------------------------------------
$dirty = git status --porcelain 2>$null
if ($dirty) {
    Write-Host ""
    Say "These files in the project folder have been changed:" "Yellow"
    Write-Host ""
    $dirty | ForEach-Object { Write-Host "  $_" }
    Stop-Here @"
Nothing was updated, because updating would overwrite those changes.

If they matter, copy them somewhere safe first. If they do not - if they are
files you did not mean to change - ask for help before discarding anything.

Your settings file (.env) is deliberately not tracked, so it is never in this
list and never at risk.
"@
}

# --------------------------------------------------------------------------
# 3. Fetch
# --------------------------------------------------------------------------
$branch = git rev-parse --abbrev-ref HEAD 2>$null
if (-not $branch) { Stop-Here "Could not work out which version of the project this is." }

Say "Fetching the newest version of '$branch'..."
$before = git rev-parse HEAD 2>$null

git pull origin $branch
if ($LASTEXITCODE -ne 0) {
    Stop-Here @"
The update did not finish.

The commonest reason is no internet connection. The platform still works with
what you already have - close this and press Start.
"@
}

$after = git rev-parse HEAD 2>$null

if ($before -eq $after) {
    Write-Host ""
    Say "Already up to date. Nothing to rebuild." "Green"
    Write-Host ""
    Read-Host "Press Enter to close this window"
    exit 0
}

Write-Host ""
Say "What changed:" "White"
Write-Host ""
git log --oneline --no-decorate "$before..$after" | ForEach-Object { Write-Host "  $_" }
Write-Host ""

# --------------------------------------------------------------------------
# 4. Rebuild
# --------------------------------------------------------------------------
# Rebuilding now rather than on the next start means the wait happens when
# somebody is sitting in front of an update, not when they are trying to open
# the platform to do something.
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Say "Rebuilding the backend. This can take a few minutes." "White"
    docker compose build
    if ($LASTEXITCODE -ne 0) {
        Stop-Here @"
The rebuild failed. The messages above say why.

Nothing was lost - your data is untouched, and the previous version is still
installed. Send the messages above on if they are not obvious.
"@
    }
    Say "Backend rebuilt." "Green"
} else {
    Say "Docker is not installed, so the backend was not rebuilt." "Yellow"
}

# The website's dependencies change less often, but when they do, a start that
# skips this fails with an error about a missing module that means nothing.
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host ""
    Say "Updating the website's parts..." "White"
    Push-Location (Join-Path $Root "frontend")
    npm install
    $npmOk = ($LASTEXITCODE -eq 0)
    Pop-Location
    if ($npmOk) {
        Say "Website updated." "Green"
    } else {
        Say "The website's parts did not update cleanly. The messages above say why." "Yellow"
    }
}

Write-Host ""
Say "Updated. Close this window and press Start." "Green"
Write-Host ""
Say "Your records, photographs and settings were not touched. If this version" "Gray"
Say "needs to change the database, it does that by itself on the next start." "Gray"
Write-Host ""
Read-Host "Press Enter to close this window"
