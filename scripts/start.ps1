# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# Start the whole platform: Docker, the backend, the website, the browser.
#
# Do not run this file directly - double-click "Start Stratum.cmd" in the
# project folder instead. Windows opens a .ps1 in Notepad rather than running
# it, which is a security default worth keeping.
#
# What it does, in order:
#
#   1. Checks the settings file exists.
#   2. Starts Docker Desktop if it is not already running, and waits for it.
#   3. Fetches any new version of the project (skipped if you have edits).
#   4. Builds and starts the backend, and waits until it actually answers.
#   5. Starts the website and opens it.
#
# Closing the window stops the website. The backend keeps running in Docker;
# "Stop Stratum.cmd" shuts that down.

$ErrorActionPreference = "Stop"

# The project folder is this script's parent, so the launcher works from
# anywhere - including a shortcut on the desktop.
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

function Say([string]$Text, [string]$Colour = "Gray") {
    Write-Host $Text -ForegroundColor $Colour
}

# The backend's own log, when it is the backend that went wrong.
#
# Docker Compose only ever says the container is unhealthy, which is a symptom
# and never a reason. The reason is always in the container's log, and telling
# somebody to go and run `docker compose logs api` themselves is asking them to
# learn Docker in the middle of a problem. So print it here.
function Show-ApiLog {
    Write-Host ""
    Write-Host "What the backend itself said:" -ForegroundColor Yellow
    Write-Host "-------------------------------------------------------" -ForegroundColor Yellow
    try {
        docker compose @script:ComposeFiles logs --tail 60 --no-color api
    } catch {
        Write-Host "(could not read the log)" -ForegroundColor Yellow
    }
    Write-Host "-------------------------------------------------------" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "The last few lines are the ones that matter. If it is not" -ForegroundColor Gray
    Write-Host "obvious, copy them out and send them on - that block is" -ForegroundColor Gray
    Write-Host "enough to say exactly what went wrong." -ForegroundColor Gray
}

function Fail([string]$Text, [switch]$WithApiLog) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Red
    if ($WithApiLog) { Show-ApiLog }
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host ""
Say "Stratum" "White"
Say "Archaeological research and collections platform"
Write-Host ""

# --------------------------------------------------------------------------
# 1. Settings
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Which compose files to use
#
# docker-compose.storage.yml puts the uploaded photographs and the backups in a
# folder you choose rather than inside Docker's own area. It is opt-in, and the
# way you opt in is by setting DATA_ROOT in .env - which is no use at all if
# the launcher never passes the file. So: if DATA_ROOT is set, it is used.
#
# Reading .env here rather than trusting the environment, because a variable
# set in .env is not set in this PowerShell session; Compose reads that file
# itself, and by then it is too late to decide which files to read.
# --------------------------------------------------------------------------
function Get-ComposeFiles([string[]]$Base) {
    $files = @()
    foreach ($name in $Base) { $files += @("-f", $name) }

    $envPath = Join-Path $Root ".env"
    if (Test-Path $envPath) {
        foreach ($line in Get-Content $envPath) {
            if ($line -match '^\s*DATA_ROOT\s*=\s*(.+?)\s*$') {
                $value = $matches[1].Trim('"').Trim("'")
                if ($value) {
                    $files += @("-f", "docker-compose.storage.yml")
                    Say "Files and backups go to $value" "DarkGray"

                    # Docker will create a missing folder, but as root - and
                    # then it cannot be opened in Explorer without a fight.
                    # Better to make it here, or say so plainly.
                    if (-not (Test-Path $value)) {
                        try {
                            New-Item -ItemType Directory -Path $value -Force | Out-Null
                            Say "  Created it." "DarkGray"
                        } catch {
                            Say "  That folder does not exist and could not be created." "Yellow"
                            Say "  Create it yourself, or change DATA_ROOT in .env." "Yellow"
                        }
                    }
                }
                break
            }
        }
    }
    return ,$files
}

if (-not (Test-Path (Join-Path $Root "docker-compose.yml"))) {
    Fail "This does not look like the project folder. Expected to find docker-compose.yml next to the scripts folder."
}

# Decided once, used by every command below - including the one that prints the
# log when something fails, which has to read the same containers that were
# started or it reports on nothing.
$script:ComposeFiles = Get-ComposeFiles @("docker-compose.yml")

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Fail @"
No settings file yet.

Right-click 'setup.ps1' in this folder and choose 'Run with PowerShell'
first. It creates the .env file and shows you the password to sign in with.
"@
}

# --------------------------------------------------------------------------
# 2. Docker
# --------------------------------------------------------------------------

# `docker info` is the honest test. The Desktop app can be open while its
# engine is still starting, and a compose command sent in that window fails
# with a confusing pipe error rather than "please wait".
function Test-DockerReady {
    try {
        docker info 2>&1 | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail @"
Docker is not installed.

Download Docker Desktop from https://www.docker.com/products/docker-desktop/
install it, then run this again.
"@
}

if (Test-DockerReady) {
    Say "Docker is running." "Green"
} else {
    Say "Starting Docker Desktop..." "Yellow"

    # Built from whichever of these variables actually exist. On Windows for
    # ARM there is no ProgramFiles(x86), and Join-Path on an unset variable
    # throws - turning "Docker is not where I expected" into a PowerShell
    # stack trace, which is the least useful thing this could show somebody.
    $bases = @(
        @{ Root = $env:ProgramFiles;         Tail = "Docker\Docker\Docker Desktop.exe" }
        @{ Root = ${env:ProgramFiles(x86)};  Tail = "Docker\Docker\Docker Desktop.exe" }
        @{ Root = $env:LOCALAPPDATA;         Tail = "Docker\Docker Desktop.exe" }
    )
    $exe = $null
    foreach ($base in $bases) {
        if ([string]::IsNullOrWhiteSpace($base.Root)) { continue }
        $candidate = Join-Path $base.Root $base.Tail
        if (Test-Path $candidate) { $exe = $candidate; break }
    }

    if ($exe) {
        Start-Process -FilePath $exe | Out-Null
    } else {
        Say "  Could not find Docker Desktop to start it. Open it yourself and leave this running." "Yellow"
    }

    # Docker Desktop takes a while on a cold start, and longer on the first
    # run after a Windows update. Three minutes is generous rather than
    # optimistic; the alternative is a launcher that gives up on a slow laptop.
    $deadline = (Get-Date).AddMinutes(3)
    $spin = 0
    while (-not (Test-DockerReady)) {
        if ((Get-Date) -gt $deadline) {
            Fail @"
Docker Desktop did not finish starting within three minutes.

Open it from the Start menu and wait until the whale icon in the system tray
stops animating, then run this again.
"@
        }
        $spin++
        Write-Host "`r  waiting for the Docker engine... $($spin * 3)s" -NoNewline
        Start-Sleep -Seconds 3
    }
    Write-Host "`r                                          `r" -NoNewline
    Say "Docker is running." "Green"
}

# --------------------------------------------------------------------------
# 3. Newer version, if there is one
# --------------------------------------------------------------------------
if (Get-Command git -ErrorAction SilentlyContinue) {
    # Never overwrite work in progress. Somebody who has edited a file wants
    # to know about it, not to have a launcher quietly stash or clobber it.
    $dirty = git status --porcelain 2>$null
    if ($dirty) {
        Say "You have unsaved changes in the project folder, so it was not updated." "Yellow"
    } else {
        $branch = git rev-parse --abbrev-ref HEAD 2>$null
        if ($branch) {
            Say "Checking for a newer version..."
            git pull origin $branch --quiet 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Say "Up to date." "Green"
            } else {
                Say "Could not check for updates (no internet?). Carrying on with what you have." "Yellow"
            }
        }
    }
}

# --------------------------------------------------------------------------
# 4. The backend
# --------------------------------------------------------------------------
Write-Host ""
Say "Starting the backend. The first run after an update takes a few minutes." "White"

# --build every time. Rebuilding is nearly instant when nothing has changed -
# Docker reuses its cached layers - and skipping it is the single most
# common way to end up running last week's code with this week's database.
docker compose @script:ComposeFiles up --build -d
if ($LASTEXITCODE -ne 0) {
    Fail "The backend did not start." -WithApiLog
}

# Up is not the same as ready: the container still has migrations to run.
Say "Waiting for the backend to be ready..."
$deadline = (Get-Date).AddMinutes(3)
$ready = $false
while (-not $ready) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        # Not up yet. Expected, repeatedly, for the first half-minute.
    }
    if ((Get-Date) -gt $deadline) {
        Fail "The backend started but never answered." -WithApiLog
    }
    Start-Sleep -Seconds 2
}
Say "Backend ready." "Green"

# --------------------------------------------------------------------------
# 5. The website
# --------------------------------------------------------------------------
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail @"
Node.js is not installed.

Download the LTS version from https://nodejs.org/ install it, close this
window, and run this again.
"@
}

Set-Location -Path (Join-Path $Root "frontend")

if (-not (Test-Path "node_modules")) {
    Write-Host ""
    Say "Installing the website's parts. This happens once and takes a minute." "White"
    npm install
    if ($LASTEXITCODE -ne 0) { Fail "npm install failed. The messages above say why." }
}

Write-Host ""
Say "Opening http://localhost:5173" "Green"
Write-Host ""
Say "Leave this window open while you use the platform." "White"
Say "Closing it stops the website. To stop the backend too, run 'Stop Stratum.cmd'."
Write-Host ""

# Give Vite a moment to bind the port before the browser asks for it,
# otherwise the first load is a connection error the user has to refresh past.
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 4
    Start-Process "http://localhost:5173"
} | Out-Null

npm run dev
