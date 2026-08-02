# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# Does the platform's e-mail actually work?
#
# Do not run this directly - double-click "Check Email.cmd" instead.
#
# The alternative to this script is: paste a password into a file, restart the
# server, invite a colleague, and wait to see whether anything arrives - with
# nothing to look at in between if it does not. This takes a couple of seconds
# and ends with a yes or a no.
#
# It prints the length of the password and never the password, so the output is
# safe to paste into a message when asking for help.

$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

function Say([string]$Text, [string]$Colour = "Gray") { Write-Host $Text -ForegroundColor $Colour }

Write-Host ""
Say "Stratum - e-mail check" "White"
Write-Host ""

if (-not (Test-Path (Join-Path $Root "docker-compose.yml"))) {
    Say "This does not look like the project folder." "Red"
    exit 1
}

try { docker info 2>&1 | Out-Null } catch { }
if ($LASTEXITCODE -ne 0) {
    Say "Docker is not running." "Yellow"
    Say "Start Docker Desktop, then run this again." "Yellow"
    exit 1
}

# The settings are read inside the container, which is the only place that
# matters. Checking them on this computer would test a copy of the file the
# platform never reads.
$composeArgs = @("-f", "docker-compose.yml")
if (Test-Path (Join-Path $Root "docker-compose.prod.yml")) {
    $composeArgs += @("-f", "docker-compose.prod.yml")
}

$running = & docker compose @composeArgs ps --status running --services 2>$null
if ($running -notcontains "api") {
    Say "The platform is not running, so there is nothing to ask." "Yellow"
    Say "Start it first, then run this again." "Yellow"
    exit 1
}

# An address to send a test message to. Blank is fine - it then only checks
# that the server accepts the account, which is where it usually goes wrong.
Write-Host "Send a test message to which address?" -ForegroundColor White
Write-Host "  Leave this blank to only check that the account signs in." -ForegroundColor DarkGray
$recipient = Read-Host "  Address"
Write-Host ""

$command = @("compose") + $composeArgs + @("exec", "-T", "api", "python", "scripts/check_email.py")
if ($recipient) { $command += $recipient }

& docker @command

Write-Host ""
Say "If it said the password was rejected: it must be a Google App Password," "DarkGray"
Say "sixteen letters with no spaces - your ordinary Gmail password will never" "DarkGray"
Say "work here. Set it in the .env file beside this folder's docker-compose.yml" "DarkGray"
Say "and start the platform again so it is read." "DarkGray"
Write-Host ""
