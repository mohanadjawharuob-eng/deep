# Serve the platform to everyone on the same WiFi.
#
# Do not run this directly — double-click "Share on WiFi.cmd" instead.
#
# The difference from "Start Stratum.cmd": that one runs a development setup
# only this computer can reach. This one builds the interface properly, serves
# it on the normal web port, and prints the address for other people to type.
#
# Nobody else installs anything. They open a browser at the address this
# prints. Everyone shares one database, so a record catalogued on one machine
# is on every other machine the moment they refresh.

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

Write-Host ""
Say "Stratum - share on this network" "White"
Write-Host ""

if (-not (Test-Path (Join-Path $Root "docker-compose.yml"))) {
    Fail "This does not look like the project folder."
}
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Fail "No settings file yet. Run setup.ps1 first."
}

# --------------------------------------------------------------------------
# This machine's address on the network
# --------------------------------------------------------------------------

# The adapter with a default gateway is the one actually on the network. A
# laptop typically also has virtual adapters from Docker, VPNs and WSL, whose
# addresses are real but reach nobody — handing one of those to a colleague
# produces a page that never loads and no clue why.
function Get-LanAddress {
    try {
        $candidates = Get-NetIPConfiguration -ErrorAction Stop |
            Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
            ForEach-Object { $_.IPv4Address.IPAddress } |
            Where-Object { $_ -and $_ -notmatch '^169\.254\.' }

        if ($candidates) { return @($candidates)[0] }
    } catch {
        # Get-NetIPConfiguration is Windows-only and absent on older builds.
    }

    try {
        $fallback = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)' -and
                $_.IPAddress -notmatch '^169\.254\.'
            } |
            ForEach-Object { $_.IPAddress }
        if ($fallback) { return @($fallback)[0] }
    } catch { }

    return $null
}

$ip = Get-LanAddress

if (-not $ip) {
    Say "Could not work out this computer's address on the network." "Yellow"
    Say "Run 'ipconfig' in a terminal and look for 'IPv4 Address'." "Yellow"
    Write-Host ""
    $ip = Read-Host "Type it here"
    if (-not $ip) { Fail "No address given, so there is nothing to share." }
}

Say "This computer is $ip on the network." "Green"

# --------------------------------------------------------------------------
# A name that survives the address changing
# --------------------------------------------------------------------------

# The router hands out addresses on a lease, so this machine's number can
# change after a reboot or overnight — and then every bookmark and every
# printed QR code points at nothing.
#
# The computer's *name* does not change. Windows answers to it on a local
# network, and so do Macs, iPhones and Androids via the `.local` form. Using
# the name as the platform's address means an address change costs nobody
# anything, which is a better answer than restarting on a timer and hoping.
$computerName = $env:COMPUTERNAME
$nameUrl = "http://$computerName"
$dotLocal = "http://$computerName.local"

# --------------------------------------------------------------------------
# Record it in the settings
# --------------------------------------------------------------------------

# The platform prints its own address into QR codes and e-mails, so it has to
# be told the one people actually type — not localhost, which would send
# somebody scanning a label to their own machine.
#
# The *name* goes in, not the number, so a printed label outlives the lease.
$envPath = Join-Path $Root ".env"
$lines = Get-Content $envPath
$wanted = @{ "SITE_ADDRESS" = ":80"; "PUBLIC_URL" = $nameUrl }

foreach ($key in $wanted.Keys) {
    $value = "$key=$($wanted[$key])"
    if ($lines -match "^\s*$key\s*=") {
        $lines = $lines -replace "^\s*$key\s*=.*$", $value
    } else {
        $lines += $value
    }
}
Set-Content -Path $envPath -Value $lines -Encoding UTF8

# --------------------------------------------------------------------------
# Docker
# --------------------------------------------------------------------------
function Test-DockerReady {
    try { docker info 2>&1 | Out-Null; return $LASTEXITCODE -eq 0 } catch { return $false }
}

if (-not (Test-DockerReady)) {
    Say "Starting Docker Desktop..." "Yellow"

    $bases = @(
        @{ Root = $env:ProgramFiles;        Tail = "Docker\Docker\Docker Desktop.exe" }
        @{ Root = ${env:ProgramFiles(x86)}; Tail = "Docker\Docker\Docker Desktop.exe" }
        @{ Root = $env:LOCALAPPDATA;        Tail = "Docker\Docker Desktop.exe" }
    )
    foreach ($base in $bases) {
        if ([string]::IsNullOrWhiteSpace($base.Root)) { continue }
        $candidate = Join-Path $base.Root $base.Tail
        if (Test-Path $candidate) { Start-Process -FilePath $candidate | Out-Null; break }
    }

    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Test-DockerReady)) {
        if ((Get-Date) -gt $deadline) {
            Fail "Docker Desktop did not finish starting. Open it, wait for it to settle, and try again."
        }
        Start-Sleep -Seconds 3
    }
}
Say "Docker is running." "Green"

# --------------------------------------------------------------------------
# Build and serve
# --------------------------------------------------------------------------
Write-Host ""
Say "Building. The first time takes several minutes; after that it is quick." "White"
Write-Host ""

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
if ($LASTEXITCODE -ne 0) { Fail "It did not start. The messages above say why." }

Say "Waiting for it to be ready..."
$deadline = (Get-Date).AddMinutes(3)
$ready = $false
while (-not $ready) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost/api/v1/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    if ((Get-Date) -gt $deadline) {
        Fail "It started but never answered. Run 'docker compose logs api' to see why."
    }
    Start-Sleep -Seconds 2
}

Write-Host ""
Say "-------------------------------------------------------" "White"
Say "  Anyone on this WiFi can now open:" "White"
Write-Host ""
Say "      $nameUrl" "Green"
Write-Host ""
Say "  or, if that does not work for them:" "Gray"
Say "      $dotLocal" "Gray"
Say "      http://$ip" "Gray"
Write-Host ""
Say "-------------------------------------------------------" "White"
Write-Host ""
Say "Give out the first one." "White"
Say "The number can change when the router restarts; the name"
Say "does not. That is why labels and links use the name."
Write-Host ""
Say "They install nothing. They just type that address."
Say "Everyone shares one database, so a record added on one"
Say "machine appears on every other one when it refreshes."
Write-Host ""
Say "Give each person their own account rather than sharing" "Yellow"
Say "yours: the platform records who changed what, and that" "Yellow"
Say "is worth nothing if everybody is you." "Yellow"
Write-Host ""
Say "Two things to know:"
Say "  - This computer must stay on and awake."
Say "  - Windows may ask to allow Docker through the firewall."
Say "    Say yes, for private networks."
Write-Host ""
Say "It keeps running after you close this window."
Say "'Stop Stratum.cmd' shuts it down."
Write-Host ""

Start-Process $nameUrl
Read-Host "Press Enter to close this window"
