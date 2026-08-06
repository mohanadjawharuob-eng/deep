# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# Where the data goes.
#
# Do not run this directly - double-click "Where Data Goes.cmd" instead.
#
# Three folders, and they are not the same decision:
#
#   Files     photographs, drone imagery, 3D models, scans, documents. This is
#             the part that grows to hundreds of gigabytes and the part you
#             would be most upset to lose.
#   Backups   nightly dumps of the records. Small - a few hundred megabytes even
#             for a large catalogue - and worth nothing on the same disk as the
#             thing they back up.
#   Database  the records themselves. Handled differently and deliberately; see
#             the note at the end of this script and what it prints.
#
# This writes two lines to the .env file and, if you ask it to, copies what is
# already stored into the new place before switching. It never deletes anything.

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

function Say([string]$Text, [string]$Colour = "Gray") { Write-Host $Text -ForegroundColor $Colour }
function Head([string]$Text) { Write-Host ""; Write-Host $Text -ForegroundColor White; Write-Host "" }

function Fail([string]$Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

Head "Stratum - where the data goes"

if (-not (Test-Path (Join-Path $Root "docker-compose.yml"))) {
    Fail "This does not look like the project folder."
}
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Fail @"
No settings file yet.

Right-click 'setup.ps1' in this folder and choose 'Run with PowerShell'
first. It creates the .env file. Then run this again.
"@
}

# --------------------------------------------------------------------------
# Reading and writing .env
#
# Line-based rather than parsed: the file is full of comments that explain what
# each setting is for, and rewriting it from a dictionary would throw them away.
# --------------------------------------------------------------------------
function Get-EnvValue([string]$Key) {
    foreach ($line in Get-Content ".env" -Encoding UTF8) {
        if ($line -match "^\s*$Key\s*=\s*(.*?)\s*$") { return $matches[1].Trim('"').Trim("'") }
    }
    return ""
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $lines = Get-Content ".env" -Encoding UTF8
    $written = $false
    $updated = foreach ($line in $lines) {
        # Matches the setting, and the conventional commented-out form of it
        # (`#KEY=`, no space), so setting a value uncomments the line already
        # there rather than leaving two lines that disagree.
        #
        # Deliberately does *not* match `#   KEY=...` with spaces after the
        # hash: that shape is an example inside a paragraph of explanation, and
        # eating it would leave the setting with no note saying what it does.
        if ($line -match "^\s*#?$Key\s*=") {
            if (-not $written) { $written = $true; "$Key=$Value" }
        } else {
            $line
        }
    }
    if (-not $written) { $updated = $updated + @("$Key=$Value") }

    [System.IO.File]::WriteAllLines(
        (Join-Path (Get-Location) ".env"),
        $updated,
        (New-Object System.Text.UTF8Encoding $false)
    )
}

# --------------------------------------------------------------------------
# The folder picker
#
# A dialog rather than a typed path. Somebody who has just been told to "set
# DATA_ROOT in .env" has already been asked to do two unfamiliar things; asking
# them to also type a path correctly, with the right slashes, is a third.
# --------------------------------------------------------------------------
Add-Type -AssemblyName System.Windows.Forms | Out-Null

function Choose-Folder([string]$Prompt, [string]$StartAt) {
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $Prompt
    $dialog.ShowNewFolderButton = $true
    if ($StartAt -and (Test-Path $StartAt)) { $dialog.SelectedPath = $StartAt }

    # TopMost, or the dialog opens behind the console window and looks like a
    # script that hung.
    $owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true }
    $result = $dialog.ShowDialog($owner)
    $owner.Dispose()

    if ($result -ne [System.Windows.Forms.DialogResult]::OK) { return "" }
    return $dialog.SelectedPath
}

# Compose reads forward slashes on every platform; backslashes in a volume
# path are a source of failures that report themselves as "invalid mount".
function To-ComposePath([string]$Path) { return $Path.Replace("\", "/") }

function Drive-Of([string]$Path) {
    if ($Path -match "^([A-Za-z]):") { return $matches[1].ToUpper() }
    return ""
}

# --------------------------------------------------------------------------
# What is set now
# --------------------------------------------------------------------------
$currentData = Get-EnvValue "DATA_ROOT"
$currentBackup = Get-EnvValue "BACKUP_ROOT"

Say "Files and photographs" "White"
if ($currentData) { Say "  $currentData" "Green" }
else { Say "  Inside Docker's own storage (on C:, wherever else you put things)" "Yellow" }

Say "Backups" "White"
if ($currentBackup) { Say "  $currentBackup" "Green" }
elseif ($currentData) { Say "  $currentData/backups - same disk as the files" "Yellow" }
else { Say "  Inside Docker's own storage" "Yellow" }
Write-Host ""

# --------------------------------------------------------------------------
# 1. Files
# --------------------------------------------------------------------------
Say "A folder picker will open. Choose where the photographs and files should live." "White"
Say "Press Cancel in it to leave that setting alone." "DarkGray"
Write-Host ""
Read-Host "Press Enter to choose the folder for files"

$dataFolder = Choose-Folder "Where should Stratum keep photographs and files?" $currentData
if ($dataFolder) {
    New-Item -ItemType Directory -Path $dataFolder -Force | Out-Null
    Say "Files will go to $dataFolder" "Green"
} else {
    Say "Left the files setting alone." "DarkGray"
}

# --------------------------------------------------------------------------
# 2. Backups
# --------------------------------------------------------------------------
Write-Host ""
Say "Now the backups." "White"
Say "A backup on the same disk as the thing it backs up is a copy, not a backup:" "DarkGray"
Say "it survives somebody deleting a record, and does not survive the disk failing." "DarkGray"
Say "Any second drive beats none. The dumps are small." "DarkGray"
Write-Host ""
Read-Host "Press Enter to choose the folder for backups"

$backupFolder = Choose-Folder "Where should the nightly backups go? Ideally a different drive." $currentBackup
if ($backupFolder) {
    New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null

    $chosenData = if ($dataFolder) { $dataFolder } else { $currentData }
    $dataDrive = Drive-Of $chosenData
    $backupDrive = Drive-Of $backupFolder
    if ($dataDrive -and $backupDrive -and $dataDrive -eq $backupDrive) {
        Say "Note: that is the same drive (${backupDrive}:) as the files." "Yellow"
        Say "It protects against a deleted record. It does not protect against the disk failing." "Yellow"
    } else {
        Say "Backups will go to $backupFolder" "Green"
    }
} else {
    Say "Left the backups setting alone." "DarkGray"
}

if (-not $dataFolder -and -not $backupFolder) {
    Write-Host ""
    Say "Nothing was changed." "Yellow"
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 0
}

# --------------------------------------------------------------------------
# 3. Move what is already stored
#
# The trap this exists to avoid: switching the setting without moving the files
# leaves every photograph already uploaded sitting in Docker's volume, still on
# disk and no longer found. The records point at files the platform will report
# as missing, which reads exactly like data loss.
# --------------------------------------------------------------------------
$dockerRunning = $false
try { docker info 2>&1 | Out-Null; $dockerRunning = ($LASTEXITCODE -eq 0) } catch { }

if ($dataFolder -and $dockerRunning) {
    $existing = & docker volume ls --quiet --filter "name=uploads" 2>$null
    if ($existing) {
        Write-Host ""
        Say "There are files already stored in Docker's volume." "White"
        Say "They should be copied across, or the platform will report them as missing." "White"
        $answer = Read-Host "Copy them to the new folder now? (Y/n)"
        if ($answer -eq "" -or $answer -match "^[Yy]") {
            Say "Copying. This can take a while for a large collection..." "DarkGray"

            $volume = ($existing -split "`n")[0].Trim()
            $target = To-ComposePath $dataFolder

            # A throwaway container with both mounted. `cp -an` never
            # overwrites: run twice and nothing is clobbered, and a half-copy
            # that is run again finishes rather than starting over.
            & docker run --rm `
                -v "${volume}:/from" `
                -v "${target}/uploads:/to" `
                alpine sh -c "mkdir -p /to && cp -an /from/. /to/ 2>/dev/null; echo done"

            if ($LASTEXITCODE -eq 0) {
                Say "Copied. The originals are still in Docker's volume - nothing was deleted." "Green"
            } else {
                Say "The copy did not finish. Your files are untouched in Docker's volume." "Yellow"
                Say "The setting has not been written, so nothing is lost. Try again." "Yellow"
                Write-Host ""
                Read-Host "Press Enter to close"
                exit 1
            }
        } else {
            Say "Not copied. Files uploaded before now will be reported as missing." "Yellow"
        }
    }
}

# --------------------------------------------------------------------------
# 4. Write it
# --------------------------------------------------------------------------
if ($dataFolder) { Set-EnvValue "DATA_ROOT" (To-ComposePath $dataFolder) }
if ($backupFolder) { Set-EnvValue "BACKUP_ROOT" (To-ComposePath $backupFolder) }

Write-Host ""
Say "Saved." "Green"
Say "Start the platform again and it will use the new folders." "White"

# --------------------------------------------------------------------------
# 5. The database, which is a different problem
# --------------------------------------------------------------------------
Write-Host ""
Say "-----------------------------------------------------------------" "DarkGray"
Say "The database" "White"
Write-Host ""
Say "The records themselves are not moved by this, on purpose." "Gray"
Write-Host ""
Say "PostgreSQL needs a real filesystem with real file locking. On Windows a" "Gray"
Say "folder handed to a Linux container is neither - it goes through a" "Gray"
Say "translation layer that is markedly slower and has been known to corrupt a" "Gray"
Say "database under load. Pointing it at D: would be trading a full disk for a" "Gray"
Say "corrupt catalogue, which is the worse of the two." "Gray"
Write-Host ""
Say "It is also the small part. Fifty thousand objects is a few hundred" "Gray"
Say "megabytes of database and several hundred gigabytes of photographs, and" "Gray"
Say "the photographs are what just moved." "Gray"
Write-Host ""
Say "If the database itself must leave C:, the supported way is to move" "White"
Say "Docker's whole disk - Docker Desktop does it safely, this script cannot:" "White"
Write-Host ""
Say "  Docker Desktop -> Settings -> Resources -> Advanced" "Cyan"
Say "  -> Disk image location -> Browse -> Apply and restart" "Cyan"
Write-Host ""
Say "That moves the database and everything else Docker stores, in one go," "Gray"
Say "using Docker's own mechanism. Stop the platform first." "Gray"
Write-Host ""
