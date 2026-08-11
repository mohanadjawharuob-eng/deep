# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# Shut the platform down.
#
# Two halves stop separately, which is worth saying out loud because it is the
# commonest confusion: closing the window that runs the website stops the
# website, and the backend carries on in Docker. That is usually what you want
# - reopening is then instant - and occasionally not, which is what this is
# for.
#
# It deletes nothing. Records, photographs and settings are on disk and stay
# there; this stops the programs that serve them.

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

function Say([string]$Text, [string]$Colour = "Gray") {
    Write-Host $Text -ForegroundColor $Colour
}

Write-Host ""
Say "Stopping Stratum" "White"
Say "----------------" "White"
Write-Host ""

# The website first. It is a plain Node process holding port 5173, started by
# `npm run dev` in its own window - a window somebody may well have already
# closed, so finding nothing here is an ordinary outcome and not a failure.
$stoppedWeb = $false
try {
    $listeners = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        $stoppedWeb = $true
    }
} catch {
    # Get-NetTCPConnection is missing on very old Windows. Not worth failing
    # over: the window can be closed by hand, and the backend is the part that
    # keeps running unattended.
}
if ($stoppedWeb) {
    Say "Website stopped." "Green"
} else {
    Say "The website was not running." "Gray"
}

# Then the backend.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Say "Docker is not installed, so there is no backend to stop." "Yellow"
    Write-Host ""
    Read-Host "Press Enter to close this window"
    exit 0
}

Say "Stopping the backend. Your data is kept."
docker compose down

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Say "Stopped." "Green"
    Write-Host ""
    Say "Nothing was deleted. Press Start in the Stratum window when you want" "Gray"
    Say "it back - or double-click 'Start Stratum.cmd'." "Gray"
} else {
    Write-Host ""
    Say "Docker reported a problem while stopping. The messages above say what." "Yellow"
}

Write-Host ""
Read-Host "Press Enter to close this window"
