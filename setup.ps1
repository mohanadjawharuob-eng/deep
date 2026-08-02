# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# First-time setup for Windows.
#
# Right-click this file and choose "Run with PowerShell", or from a PowerShell
# window in this folder run:
#
#     powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Creates the .env file the platform needs, with strong random values filled in
# for you, and prints the password you will sign in with. It writes exactly one
# file (.env) in this folder and nothing else.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "Archaeological Research Platform - setup" -ForegroundColor White
Write-Host "----------------------------------------"
Write-Host ""

if (-not (Test-Path ".env.example")) {
    Write-Host "Could not find .env.example. Run this from inside the project folder." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

if (Test-Path ".env") {
    Write-Host "A .env file already exists." -ForegroundColor Yellow
    $reply = Read-Host "Replace it with fresh settings? Your current passwords will be lost. [y/N]"
    if ($reply -notmatch '^[yY]') {
        Write-Host "Left your existing .env alone. Nothing changed."
        Read-Host "Press Enter to close"
        exit 0
    }
}

function New-RandomString {
    param([int]$Length)

    # Letters and digits only: the value ends up in a .env file and in a
    # database URL, where punctuation would need escaping.
    $alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

    # RandomNumberGenerator::Create() exists on both .NET Framework - which is
    # what Windows PowerShell 5.1 runs on, and 5.1 is what Windows ships by
    # default - and modern .NET. The static Fill() method does not: it is .NET
    # Core 2.1 and later only, so calling it fails on a stock Windows machine.
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $result = New-Object System.Text.StringBuilder

        # 62 characters do not divide 256 evenly. Values landing in the final
        # partial block are discarded rather than wrapped, so every character
        # stays equally likely instead of the first few being slightly favoured.
        $limit = 256 - (256 % $alphabet.Length)
        $buffer = New-Object byte[] 1

        while ($result.Length -lt $Length) {
            $rng.GetBytes($buffer)
            if ($buffer[0] -lt $limit) {
                [void]$result.Append($alphabet[$buffer[0] % $alphabet.Length])
            }
        }
        $result.ToString()
    }
    finally {
        $rng.Dispose()
    }
}

$secretKey    = New-RandomString -Length 64
$dbPassword   = New-RandomString -Length 24
# Built to satisfy the password policy by construction - at least ten
# characters with upper case, lower case and a digit.
$adminPassword = "Dig" + (New-RandomString -Length 12) + "7x"

Copy-Item ".env.example" ".env" -Force

# Read as lines, swap the four values, write back as UTF-8 without a byte-order
# mark: a BOM would end up inside the first variable's name and break parsing.
#
# ``-Encoding UTF8`` is needed because Windows PowerShell 5.1 otherwise reads a
# UTF-8 file as the system code page, which garbles the punctuation in the
# template's comments on the round trip.
$lines = Get-Content ".env" -Encoding UTF8
$replacements = @{
    "SECRET_KEY"           = $secretKey
    "POSTGRES_PASSWORD"    = $dbPassword
    "FIRST_ADMIN_PASSWORD" = $adminPassword
    "SEED_SAMPLE_DATA"     = "true"
}
$updated = $lines | ForEach-Object {
    $line = $_
    foreach ($key in $replacements.Keys) {
        if ($line -match "^$key=") { $line = "$key=$($replacements[$key])" }
    }
    $line
}
[System.IO.File]::WriteAllLines(
    (Join-Path (Get-Location) ".env"),
    $updated,
    (New-Object System.Text.UTF8Encoding $false)
)

Write-Host "Settings created." -ForegroundColor Green
Write-Host ""
Write-Host "Write these down - you need them to sign in:" -ForegroundColor White
Write-Host ""
Write-Host "    Address:   http://localhost:8000/docs"
Write-Host "    E-mail:    admin@example.org"
Write-Host "    Password:  $adminPassword" -ForegroundColor Cyan
Write-Host ""
Write-Host "(They are also saved in the .env file in this folder.)"
Write-Host ""
Write-Host "Next step - start the platform:" -ForegroundColor White
Write-Host ""
Write-Host "    docker compose up --build"
Write-Host ""
Write-Host "The first run takes a few minutes while it downloads and builds."
Write-Host "It is ready when you see a line containing 'Application startup complete'."
Write-Host ""
Read-Host "Press Enter to close"
