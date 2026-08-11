# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# Take a backup of everything.
#
# The archive lives on one disk. Nothing else has a copy of it - there is no
# cloud quietly keeping one - so if that disk dies, the records die with it.
# This is the answer to that, and it is deliberately the simplest one that
# works: a folder you can copy to a memory stick, hand to somebody, or leave
# in a drawer.
#
# What goes in it:
#
#   records.sql   Every record: sites, finds, objects, people, permissions,
#                 the lot. A plain text dump, so it can be read and restored
#                 by any PostgreSQL, not only this exact version.
#   files/        Every photograph, document and 3D model, as files.
#   RESTORE.txt   How to put it back. A backup nobody knows how to restore is
#                 a folder of noise, and the instructions belong *in* it -
#                 not in a wiki nobody can reach when the disk is dead.
#
# Two things this deliberately does not do.
#
# It does not compress. A zip of a corrupted backup is a corrupted backup you
# cannot open halfway; a folder can be inspected, and a single unreadable
# photograph costs you that photograph rather than everything.
#
# It does not delete old backups. Deciding which of somebody's backups to
# destroy is not a decision a script should make quietly.

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
Say "Backing up Stratum" "White"
Say "------------------" "White"
Write-Host ""

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-Here "Docker is not installed, so there is nothing to back up from."
}

# The database has to be running to be dumped. Saying so plainly beats a
# postgres error about a socket.
$running = docker compose ps --status running --services 2>$null
if ($running -notcontains "db") {
    Stop-Here @"
The platform is not running, so the database cannot be read.

Press Start in the Stratum window, wait for it to finish, and run this again.
"@
}

# --------------------------------------------------------------------------
# Where to put it
# --------------------------------------------------------------------------
Add-Type -AssemblyName System.Windows.Forms | Out-Null

$picker = New-Object System.Windows.Forms.FolderBrowserDialog
$picker.Description = "Choose where to keep the backup - a memory stick or a second disk"
$picker.ShowNewFolderButton = $true

if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    Say "Nothing was backed up." "Yellow"
    Read-Host "Press Enter to close this window"
    exit 0
}

$stamp = Get-Date -Format "yyyy-MM-dd-HHmm"
$target = Join-Path $picker.SelectedPath "stratum-backup-$stamp"

# A backup written onto the disk it is backing up protects you from nothing.
# Saying so is the whole value of asking.
$targetDrive = [System.IO.Path]::GetPathRoot($target)
$hereDrive = [System.IO.Path]::GetPathRoot($Root)
if ($targetDrive -eq $hereDrive) {
    Write-Host ""
    Say "That is the same disk the platform is on ($targetDrive)." "Yellow"
    Say "A backup there protects you from a mistake, but not from the disk failing." "Yellow"
    Write-Host ""
    $answer = Read-Host "Carry on anyway? (y/N)"
    if ($answer -notmatch '^(y|yes)$') {
        Say "Nothing was backed up." "Yellow"
        Read-Host "Press Enter to close this window"
        exit 0
    }
}

New-Item -ItemType Directory -Path $target -Force | Out-Null
Say "Writing to $target" "White"
Write-Host ""

# --------------------------------------------------------------------------
# The records
# --------------------------------------------------------------------------
Say "1 of 3  The records..."

$dump = Join-Path $target "records.sql"
# Read straight out of the container. `--clean --if-exists` so restoring over
# an existing database works rather than colliding with it.
docker compose exec -T db pg_dump -U postgres -d archeo --clean --if-exists |
    Out-File -FilePath $dump -Encoding utf8

if ($LASTEXITCODE -ne 0 -or -not (Test-Path $dump)) {
    Stop-Here "The database could not be read. Nothing was written."
}

$dumpMb = [math]::Round((Get-Item $dump).Length / 1MB, 1)
if ((Get-Item $dump).Length -lt 1024) {
    Stop-Here @"
The database dump came out empty, which means it did not work.

Nothing else was written. Send on what is printed above.
"@
}
Say "        records.sql - $dumpMb MB" "Green"

# --------------------------------------------------------------------------
# The files
# --------------------------------------------------------------------------
Say "2 of 3  The photographs and documents..."

$files = Join-Path $target "files"
New-Item -ItemType Directory -Path $files -Force | Out-Null

# Straight out of the volume, whatever disk it was assigned to. `docker cp`
# rather than reading the host path, because the host path is a setting that
# may have been changed and the container always knows where its own files are.
docker compose cp "api:/data/uploads/." $files 2>$null
if ($LASTEXITCODE -ne 0) {
    Say "        Could not copy the files. The records were still saved." "Yellow"
} else {
    $count = (Get-ChildItem -Path $files -Recurse -File -ErrorAction SilentlyContinue).Count
    $size = (Get-ChildItem -Path $files -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    $sizeMb = if ($size) { [math]::Round($size / 1MB, 1) } else { 0 }
    Say "        $count files - $sizeMb MB" "Green"
}

# --------------------------------------------------------------------------
# How to put it back
# --------------------------------------------------------------------------
Say "3 of 3  Writing the instructions..."

$restore = @"
STRATUM BACKUP
Taken $(Get-Date -Format "dddd d MMMM yyyy, HH:mm")

WHAT IS IN HERE

  records.sql   Every record in the platform, as text.
  files\        Every photograph, document and 3D model.

PUTTING IT BACK

You need the Stratum project folder and Docker Desktop, as when you first
installed it. Then, in order:

  1. Start Docker Desktop and wait for the whale icon to settle.

  2. Open a terminal in the project folder and start only the database:

       docker compose up -d db

  3. Load the records back in. This REPLACES what is in the platform now:

       docker compose exec -T db psql -U postgres -d archeo < records.sql

     On Windows PowerShell, use this instead - PowerShell does not have "<":

       Get-Content records.sql | docker compose exec -T db psql -U postgres -d archeo

  4. Put the files back:

       docker compose up -d api
       docker compose cp "files\." api:/data/uploads

  5. Start everything the normal way, with Stratum.cmd.

IF SOMETHING GOES WRONG

Do not delete this folder. Copy it somewhere safe and ask for help with the
error message - a backup that half-restored is still a backup.

WHAT THIS DOES NOT INCLUDE

Your settings file (.env), which holds the database password and the e-mail
password. That is deliberate: it is a credential, and a backup gets carried
about on memory sticks. If you restore onto a fresh installation you will run
setup again and set a new password, which is the right thing to do anyway.
"@

$restore | Out-File -FilePath (Join-Path $target "RESTORE.txt") -Encoding utf8
Say "        RESTORE.txt" "Green"

Write-Host ""
Say "Done." "Green"
Write-Host ""
Say "The backup is at:" "White"
Say "  $target" "White"
Write-Host ""
Say "Worth doing: copy that folder somewhere that is not this building." "Gray"
Say "A backup on a stick in the same drawer as the computer survives a disk" "Gray"
Say "failure and nothing else." "Gray"
Write-Host ""

$open = Read-Host "Open the folder now? (Y/n)"
if ($open -notmatch '^(n|no)$') {
    Start-Process explorer.exe $target
}
