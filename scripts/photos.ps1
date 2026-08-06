# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# Point at a folder of photographs; they appear in the platform.
#
# Do not run this directly - double-click "Add Photos.cmd" instead.
#
# ---------------------------------------------------------------------------
# How it decides what each photograph belongs to
# ---------------------------------------------------------------------------
# From the folder names, matched against records that already exist:
#
#   <chosen folder>/
#     TED-A/                  <- a site code
#       1001/                 <- a context number on that site
#         IMG_0001.jpg        ->  site TED-A, context 1001
#         IMG_0002.jpg
#       IMG_0100.jpg          ->  site TED-A, no context
#     TED-B/
#       ...
#
# A folder whose name matches nothing is reported and skipped - never guessed
# at. Half-right attribution is worse than none: a photograph filed against the
# wrong context is evidence for a sequence that did not happen, and nothing
# later in the archive will contradict it.
#
# If the chosen folder has no sub-folders at all, it asks which site the whole
# lot belongs to.
#
# ---------------------------------------------------------------------------
# Two things it does that make it safe to run again
# ---------------------------------------------------------------------------
# **It shows the plan and waits.** Nothing is uploaded until the counts are on
# screen and you have said yes.
#
# **It keeps a list of what it has already sent**, in .stratum-uploaded.txt
# inside the chosen folder. Run it again after adding forty more photographs and
# only the forty are sent. Delete that file to force everything to be re-sent.

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
Say "Stratum - add photographs from a folder" "White"
Write-Host ""

# --------------------------------------------------------------------------
# Is it running?
# --------------------------------------------------------------------------
$ApiPort = "8000"
if (Test-Path (Join-Path $Root ".env")) {
    foreach ($line in Get-Content (Join-Path $Root ".env") -Encoding UTF8) {
        if ($line -match "^\s*API_PORT\s*=\s*(\d+)") { $ApiPort = $matches[1] }
    }
}
$Api = "http://localhost:$ApiPort/api/v1"

try {
    Invoke-RestMethod -Uri "$Api/health" -TimeoutSec 5 | Out-Null
} catch {
    # Port 80 too: "Share on WiFi" puts it behind a web server on the ordinary
    # port, and somebody who started it that way should not have to know that.
    $Api = "http://localhost/api/v1"
    try { Invoke-RestMethod -Uri "$Api/health" -TimeoutSec 5 | Out-Null }
    catch { Fail "The platform does not seem to be running. Start it first, then run this again." }
}
Say "Found the platform at $Api" "Green"

# --------------------------------------------------------------------------
# Sign in
#
# Asked for rather than read out of .env: the administrator password in that
# file is the one set at installation, and by now it may not be the one that
# works. A stored password that silently stops working is worse than a prompt.
# --------------------------------------------------------------------------
Write-Host ""
Say "Sign in with the account the photographs should be recorded against." "White"
$identifier = Read-Host "  Username or e-mail"
$secure = Read-Host "  Password" -AsSecureString
$password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
)

try {
    $session = Invoke-RestMethod -Uri "$Api/auth/login" -Method Post `
        -ContentType "application/json" `
        -Body (@{ identifier = $identifier; password = $password } | ConvertTo-Json)
} catch {
    Fail "That did not sign in. Check the username and password and try again."
}
$Token = $session.access_token
$Headers = @{ Authorization = "Bearer $Token" }
Say "Signed in." "Green"

# --------------------------------------------------------------------------
# The folder
# --------------------------------------------------------------------------
Add-Type -AssemblyName System.Windows.Forms | Out-Null

$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = "Which folder holds the photographs?"
$owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true }
Write-Host ""
Read-Host "Press Enter to choose the folder of photographs"
$chose = $dialog.ShowDialog($owner)
$owner.Dispose()
if ($chose -ne [System.Windows.Forms.DialogResult]::OK) {
    Say "Nothing chosen. Nothing was uploaded." "Yellow"
    exit 0
}
$Folder = $dialog.SelectedPath
Say "Reading $Folder" "Green"

$Extensions = @(".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic")
$files = Get-ChildItem -Path $Folder -Recurse -File |
    Where-Object { $Extensions -contains $_.Extension.ToLower() }

if (-not $files) { Fail "No images found in that folder." }
Say "$($files.Count) image files found." "Green"

# --------------------------------------------------------------------------
# What is already there
# --------------------------------------------------------------------------
$ManifestPath = Join-Path $Folder ".stratum-uploaded.txt"
$Already = @{}
if (Test-Path $ManifestPath) {
    foreach ($line in Get-Content $ManifestPath -Encoding UTF8) {
        if ($line.Trim()) { $Already[$line.Trim()] = $true }
    }
    Say "$($Already.Count) already sent on an earlier run; those will be skipped." "DarkGray"
}

# --------------------------------------------------------------------------
# The records to match against
# --------------------------------------------------------------------------
Write-Host ""
Say "Reading the sites and contexts already recorded..." "DarkGray"

$sites = @{}
$page = Invoke-RestMethod -Uri "$Api/sites?limit=200" -Headers $Headers
foreach ($site in $page.items) { $sites[$site.code.ToLower()] = $site }
Say "$($sites.Count) sites." "DarkGray"

# Contexts are fetched per site, and only for the sites this folder mentions -
# a department with forty sites should not wait for every context in the
# database to answer a question about one trench.
$contextsBySite = @{}
function Get-Contexts([string]$SiteId) {
    if ($contextsBySite.ContainsKey($SiteId)) { return $contextsBySite[$SiteId] }
    $map = @{}
    $result = Invoke-RestMethod -Uri "$Api/contexts?site_id=$SiteId&limit=200" -Headers $Headers
    foreach ($context in $result.items) { $map[$context.context_number.ToLower()] = $context }
    $contextsBySite[$SiteId] = $map
    return $map
}

# --------------------------------------------------------------------------
# Work out where each photograph goes
# --------------------------------------------------------------------------
$plan = @()
$unmatched = @{}
$skipped = 0

# A flat folder names nothing, so ask once rather than reporting every file as
# unmatched.
$hasSubfolders = (Get-ChildItem -Path $Folder -Directory | Measure-Object).Count -gt 0
$fallbackSite = $null
if (-not $hasSubfolders) {
    Write-Host ""
    Say "This folder has no sub-folders, so there is nothing to read a site from." "Yellow"
    Say "Sites:" "White"
    foreach ($code in ($sites.Keys | Sort-Object)) { Say "  $($sites[$code].code)  $($sites[$code].name)" }
    $answer = Read-Host "Which site code do these belong to? (blank to stop)"
    if (-not $answer) { Say "Stopped. Nothing was uploaded." "Yellow"; exit 0 }
    if (-not $sites.ContainsKey($answer.ToLower())) { Fail "No site with code '$answer'." }
    $fallbackSite = $sites[$answer.ToLower()]
}

foreach ($file in $files) {
    $relative = $file.FullName.Substring($Folder.Length).TrimStart("\", "/")
    if ($Already.ContainsKey($relative)) { $skipped++; continue }

    $parts = $relative -split "[\\/]"
    $site = $null
    $context = $null

    if ($fallbackSite) {
        $site = $fallbackSite
    } elseif ($parts.Count -ge 2 -and $sites.ContainsKey($parts[0].ToLower())) {
        $site = $sites[$parts[0].ToLower()]
        if ($parts.Count -ge 3) {
            $map = Get-Contexts $site.id
            if ($map.ContainsKey($parts[1].ToLower())) { $context = $map[$parts[1].ToLower()] }
        }
    }

    if (-not $site) {
        $key = if ($parts.Count -ge 2) { $parts[0] } else { "(loose in the top folder)" }
        if (-not $unmatched.ContainsKey($key)) { $unmatched[$key] = 0 }
        $unmatched[$key]++
        continue
    }

    $plan += [pscustomobject]@{
        File     = $file
        Relative = $relative
        SiteId   = $site.id
        SiteCode = $site.code
        ContextId = if ($context) { $context.id } else { $null }
        ContextNo = if ($context) { $context.context_number } else { "" }
    }
}

# --------------------------------------------------------------------------
# Show the plan, and wait
# --------------------------------------------------------------------------
Write-Host ""
Say "-----------------------------------------------------------------" "DarkGray"
Say "What would be uploaded" "White"
Write-Host ""

if ($skipped) { Say "$skipped already sent on an earlier run - skipping." "DarkGray" }

if ($plan.Count -eq 0) {
    Say "Nothing new to upload." "Yellow"
} else {
    $plan |
        Group-Object { "$($_.SiteCode)|$($_.ContextNo)" } |
        Sort-Object Name |
        ForEach-Object {
            $bits = $_.Name -split "\|"
            $where = if ($bits[1]) { "site $($bits[0]), context $($bits[1])" } else { "site $($bits[0])" }
            Say ("  {0,5}  ->  {1}" -f $_.Count, $where)
        }
}

if ($unmatched.Count) {
    Write-Host ""
    Say "Not uploaded - nothing matched these folder names:" "Yellow"
    foreach ($key in ($unmatched.Keys | Sort-Object)) {
        Say ("  {0,5}  in  {1}" -f $unmatched[$key], $key) "Yellow"
    }
    Write-Host ""
    Say "A folder has to be named exactly as the site's code, and a folder inside" "DarkGray"
    Say "it exactly as a context number on that site. Nothing is guessed at: a" "DarkGray"
    Say "photograph filed against the wrong context is evidence for a sequence" "DarkGray"
    Say "that did not happen." "DarkGray"
}

if ($plan.Count -eq 0) { Write-Host ""; Read-Host "Press Enter to close"; exit 0 }

Write-Host ""
$go = Read-Host "Upload $($plan.Count) photographs? (y/N)"
if ($go -notmatch "^[Yy]") { Say "Nothing was uploaded." "Yellow"; exit 0 }

# --------------------------------------------------------------------------
# Uploading
#
# Multipart is built by hand because Windows PowerShell 5.1 has no -Form on
# Invoke-RestMethod, and because the body has to carry raw bytes: reading a JPEG
# as a string and encoding it back mangles it in a way that only shows up as
# "not a usable image" on the far end.
# --------------------------------------------------------------------------
function Send-Photo([string]$Path, [hashtable]$Fields) {
    $boundary = [System.Guid]::NewGuid().ToString()
    $LF = "`r`n"
    $encoding = [System.Text.Encoding]::UTF8
    $stream = New-Object System.IO.MemoryStream

    foreach ($key in $Fields.Keys) {
        $value = $Fields[$key]
        if ($null -eq $value -or "$value" -eq "") { continue }
        $part = "--$boundary$LF" +
                "Content-Disposition: form-data; name=`"$key`"$LF$LF" +
                "$value$LF"
        $bytes = $encoding.GetBytes($part)
        $stream.Write($bytes, 0, $bytes.Length)
    }

    $name = [System.IO.Path]::GetFileName($Path)
    $header = "--$boundary$LF" +
              "Content-Disposition: form-data; name=`"file`"; filename=`"$name`"$LF" +
              "Content-Type: application/octet-stream$LF$LF"
    $bytes = $encoding.GetBytes($header)
    $stream.Write($bytes, 0, $bytes.Length)

    $content = [System.IO.File]::ReadAllBytes($Path)
    $stream.Write($content, 0, $content.Length)

    $bytes = $encoding.GetBytes("$LF--$boundary--$LF")
    $stream.Write($bytes, 0, $bytes.Length)

    Invoke-RestMethod -Uri "$Api/photographs" -Method Post `
        -Headers $Headers `
        -ContentType "multipart/form-data; boundary=$boundary" `
        -Body $stream.ToArray() | Out-Null
    $stream.Dispose()
}

Write-Host ""
$done = 0
$failed = @()
foreach ($item in $plan) {
    $done++
    Write-Progress -Activity "Uploading" -Status "$done of $($plan.Count): $($item.Relative)" `
        -PercentComplete (($done / $plan.Count) * 100)

    $fields = @{
        title      = [System.IO.Path]::GetFileNameWithoutExtension($item.File.Name)
        site_id    = $item.SiteId
        context_id = $item.ContextId
    }

    try {
        Send-Photo $item.File.FullName $fields
        # Appended one line at a time rather than written at the end, so a run
        # interrupted at photograph nine hundred does not re-send those nine
        # hundred next time.
        Add-Content -Path $ManifestPath -Value $item.Relative -Encoding UTF8
    } catch {
        $failed += "$($item.Relative): $($_.Exception.Message)"
    }
}
Write-Progress -Activity "Uploading" -Completed

Write-Host ""
Say "-----------------------------------------------------------------" "DarkGray"
Say "$($plan.Count - $failed.Count) uploaded." "Green"

if ($failed.Count) {
    Write-Host ""
    Say "$($failed.Count) did not upload:" "Yellow"
    $failed | Select-Object -First 20 | ForEach-Object { Say "  $_" "Yellow" }
    if ($failed.Count -gt 20) { Say "  ...and $($failed.Count - 20) more." "Yellow" }
    Write-Host ""
    Say "They are not in the already-sent list, so running this again retries them." "DarkGray"
}

Write-Host ""
Say "They are now on the site's page in the platform, with their EXIF read and" "Gray"
Say "thumbnails generated. The originals in your folder are untouched." "Gray"
Write-Host ""
