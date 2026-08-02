# What the platform said about itself.
#
# Do not run this directly — double-click "Show Log.cmd" instead.
#
# When something will not start, Docker's own message is always the same
# unhelpful sentence: "container archeo-api is unhealthy". That is a symptom.
# The reason is in the container's log, and getting at it otherwise means
# opening a terminal and knowing a Docker command — which is a lot to ask of
# somebody whose actual problem is that the platform will not open.
#
# So this prints the log, and writes it to a file that can be attached to a
# message. It changes nothing.

$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

function Say([string]$Text, [string]$Colour = "Gray") { Write-Host $Text -ForegroundColor $Colour }

Write-Host ""
Say "Stratum - log" "White"
Write-Host ""

if (-not (Test-Path (Join-Path $Root "docker-compose.yml"))) {
    Say "This does not look like the project folder." "Red"
    exit 1
}

try { docker info 2>&1 | Out-Null } catch { }
if ($LASTEXITCODE -ne 0) {
    Say "Docker is not running, so there is no log to read." "Yellow"
    Say "Start Docker Desktop, then try the platform again." "Yellow"
    exit 1
}

# Both compose files, so this reads the same containers whether the platform
# was started with "Start Stratum.cmd" or "Share on WiFi.cmd". Compose ignores
# services from the override file that are not running.
$composeArgs = @("-f", "docker-compose.yml")
if (Test-Path (Join-Path $Root "docker-compose.prod.yml")) {
    $composeArgs += @("-f", "docker-compose.prod.yml")
}

$outputPath = Join-Path $Root "stratum-log.txt"
$collected = New-Object System.Collections.Generic.List[string]

function Collect([string]$Line) {
    $collected.Add($Line) | Out-Null
}

Collect "Stratum log — $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Collect ""

# --------------------------------------------------------------------------
# What is actually running
# --------------------------------------------------------------------------
Say "What is running:" "White"
Say "-------------------------------------------------------"
Collect "WHAT IS RUNNING"
Collect "-------------------------------------------------------"

$status = & docker compose @composeArgs ps --format "table {{.Name}}\t{{.Status}}" 2>&1
foreach ($line in $status) {
    Write-Host $line
    Collect ([string]$line)
}
Write-Host ""
Collect ""

# --------------------------------------------------------------------------
# The backend, which is where nearly every failure shows up
# --------------------------------------------------------------------------
# The database and the web server rarely fail in an interesting way. The
# backend runs the migrations and reads the settings, so it is where a wrong
# value in .env or a half-applied schema turns into an error.
foreach ($service in @("api", "db", "web")) {
    Say "The $service log (last 80 lines):" "White"
    Say "-------------------------------------------------------"
    Collect "THE $($service.ToUpper()) LOG"
    Collect "-------------------------------------------------------"

    $log = & docker compose @composeArgs logs --tail 80 --no-color $service 2>&1
    if (-not $log) {
        Write-Host "(nothing — this one has not run)"
        Collect "(nothing — this one has not run)"
    } else {
        foreach ($line in $log) {
            Write-Host $line
            Collect ([string]$line)
        }
    }
    Write-Host ""
    Collect ""
}

# --------------------------------------------------------------------------
# Written out, so it can be sent rather than retyped
# --------------------------------------------------------------------------
# Deliberately no .env in here, at all. That file holds the database password,
# the signing key and — if it has been set up — the mail password, and a log
# people are encouraged to send on is the last place any of them should be.
try {
    Set-Content -Path $outputPath -Value $collected -Encoding UTF8
    Write-Host ""
    Say "-------------------------------------------------------" "White"
    Say "  The same text is saved here:" "White"
    Say "      $outputPath" "Green"
    Write-Host ""
    Say "  It contains no passwords — the settings file is not" "Gray"
    Say "  read by this at all — so it is safe to send on." "Gray"
    Say "-------------------------------------------------------" "White"
} catch {
    Say "Could not write $outputPath, but the log is above." "Yellow"
}

Write-Host ""
Say "The lines that matter are usually the last few of the api log," "White"
Say "and anything with ERROR or Traceback in it." "White"
Write-Host ""
