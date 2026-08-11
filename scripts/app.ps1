# ASCII only in this file, deliberately. Windows PowerShell 5.1 reads a .ps1
# with no byte-order mark as ANSI, not UTF-8, so a typographic dash turns into
# three mojibake characters and the script fails to parse - reporting errors on
# lines that are not the problem. Use a plain hyphen.
#
# The Stratum window: one place for everything the platform can be told to do.
#
# Before this there were eight files in the project folder, all called
# something like "Share on WiFi.cmd", and knowing which to double-click meant
# remembering what each one did. This is the same eight things as buttons, with
# the state of the platform written across the top so the first question -
# is it even running? - is answered before anything is clicked.
#
# Do not run this file directly. Double-click "Stratum.cmd" in the project
# folder: Windows opens a .ps1 in Notepad rather than running it, which is a
# security default worth keeping.
#
# The design rules the rest of the platform follows apply here too. Nothing is
# ever signalled by colour alone - every state has a word beside its dot. And
# anything the platform is unsure about is drawn provisionally rather than
# asserted: while the status is still being checked it says "checking", not
# "stopped".

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

# Nothing is on screen yet, and the console this was launched from has already
# closed. An error here would otherwise be a double-click that does nothing at
# all - the worst failure a launcher can have, because there is nothing to
# read and nothing to send on. So write it down and say where.
trap {
    $note = Join-Path $Root "stratum-launcher-error.txt"
    $text = @"
The Stratum window could not open.

$($_.Exception.Message)

$($_.ScriptStackTrace)

What to try instead: double-click "Start Stratum.cmd" in this folder. It does
the same job in a plain console window and does not need any of the parts that
failed above.
"@
    try { Set-Content -Path $note -Value $text -Encoding ASCII } catch { }
    try {
        [System.Windows.Forms.MessageBox]::Show(
            "The Stratum window could not open. The reason was written to " +
            "stratum-launcher-error.txt in the project folder.`r`n`r`n" +
            "Use 'Start Stratum.cmd' in the meantime - it does the same job in " +
            "a plain console window.",
            "Stratum", "OK", "Error") | Out-Null
    } catch {
        # No message box available either. The file is the fallback.
    }
    exit 1
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Version = "0.2.0"
$VersionFile = Join-Path $Root "VERSION"
if (Test-Path $VersionFile) {
    $read = (Get-Content -Path $VersionFile -TotalCount 1).Trim()
    if ($read) { $Version = $read }
}

# --------------------------------------------------------------------------
# The palette
#
# The platform's own: fired clay, bone, ink, oxidised bronze. The launcher
# looking like the thing it launches is not decoration - it is how somebody
# knows this window belongs to Stratum and not to Windows.
# --------------------------------------------------------------------------
$Clay      = [System.Drawing.Color]::FromArgb(139, 58, 31)
$ClayDark  = [System.Drawing.Color]::FromArgb(110, 45, 24)
$Bone      = [System.Drawing.Color]::FromArgb(242, 237, 227)
$Surface   = [System.Drawing.Color]::FromArgb(250, 248, 244)
$Ink       = [System.Drawing.Color]::FromArgb(59, 47, 36)
$Ink2      = [System.Drawing.Color]::FromArgb(107, 92, 77)
$Bronze    = [System.Drawing.Color]::FromArgb(47, 93, 80)
$Amber     = [System.Drawing.Color]::FromArgb(166, 124, 0)
$Border    = [System.Drawing.Color]::FromArgb(220, 212, 198)

$FontUi     = New-Object System.Drawing.Font("Segoe UI", 9.5)
$FontStrong = New-Object System.Drawing.Font("Segoe UI Semibold", 9.5)
$FontTitle  = New-Object System.Drawing.Font("Segoe UI", 17, [System.Drawing.FontStyle]::Bold)
$FontSmall  = New-Object System.Drawing.Font("Segoe UI", 8)

# --------------------------------------------------------------------------
# Icons, drawn rather than shipped
#
# A .ico or a set of .png files would be binary blobs in a repository that is
# otherwise entirely text - unreadable in a diff, and impossible to correct
# without an image editor. These are a dozen lines of drawing each, they take
# the button's own colour, and they redraw at whatever size is asked for.
# --------------------------------------------------------------------------
function New-Glyph {
    param(
        [string]$Name,
        [int]$Size = 20,
        [System.Drawing.Color]$Colour
    )

    $bitmap = New-Object System.Drawing.Bitmap $Size, $Size
    $g = [System.Drawing.Graphics]::FromImage($bitmap)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $pen = New-Object System.Drawing.Pen $Colour, 1.6
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $brush = New-Object System.Drawing.SolidBrush $Colour
    $s = $Size / 20.0

    switch ($Name) {
        # A triangle: play, start.
        "start" {
            $points = [System.Drawing.PointF[]]@(
                (New-Object System.Drawing.PointF (6 * $s), (4 * $s)),
                (New-Object System.Drawing.PointF (16 * $s), (10 * $s)),
                (New-Object System.Drawing.PointF (6 * $s), (16 * $s))
            )
            $g.FillPolygon($brush, $points)
        }
        # A square: stop.
        "stop" {
            $g.FillRectangle($brush, (5 * $s), (5 * $s), (10 * $s), (10 * $s))
        }
        # A browser window with an arrow leaving it.
        "open" {
            $g.DrawRectangle($pen, (3 * $s), (5 * $s), (10 * $s), (10 * $s))
            $g.DrawLine($pen, (9 * $s), (9 * $s), (17 * $s), (3 * $s))
            $g.DrawLine($pen, (12 * $s), (3 * $s), (17 * $s), (3 * $s))
            $g.DrawLine($pen, (17 * $s), (3 * $s), (17 * $s), (8 * $s))
        }
        # Radiating arcs: sharing over the network.
        "wifi" {
            $g.DrawArc($pen, (3 * $s), (5 * $s), (14 * $s), (14 * $s), 200, 140)
            $g.DrawArc($pen, (6 * $s), (8 * $s), (8 * $s), (8 * $s), 200, 140)
            $g.FillEllipse($brush, (9 * $s), (13 * $s), (2.5 * $s), (2.5 * $s))
        }
        # A camera.
        "photos" {
            $g.DrawRectangle($pen, (2.5 * $s), (6 * $s), (15 * $s), (10 * $s))
            $g.DrawLine($pen, (7 * $s), (6 * $s), (8.5 * $s), (4 * $s))
            $g.DrawLine($pen, (8.5 * $s), (4 * $s), (11.5 * $s), (4 * $s))
            $g.DrawLine($pen, (11.5 * $s), (4 * $s), (13 * $s), (6 * $s))
            $g.DrawEllipse($pen, (7 * $s), (8.5 * $s), (6 * $s), (6 * $s))
        }
        # A stack of disks.
        "disk" {
            $g.DrawEllipse($pen, (3 * $s), (3 * $s), (14 * $s), (5 * $s))
            $g.DrawLine($pen, (3 * $s), (5.5 * $s), (3 * $s), (14.5 * $s))
            $g.DrawLine($pen, (17 * $s), (5.5 * $s), (17 * $s), (14.5 * $s))
            $g.DrawArc($pen, (3 * $s), (12 * $s), (14 * $s), (5 * $s), 0, 180)
            $g.DrawArc($pen, (3 * $s), (7.5 * $s), (14 * $s), (5 * $s), 0, 180)
        }
        # An envelope.
        "mail" {
            $g.DrawRectangle($pen, (2.5 * $s), (5 * $s), (15 * $s), (10 * $s))
            $g.DrawLine($pen, (2.5 * $s), (5 * $s), (10 * $s), (11 * $s))
            $g.DrawLine($pen, (17.5 * $s), (5 * $s), (10 * $s), (11 * $s))
        }
        # A page with ruled lines.
        "log" {
            $g.DrawRectangle($pen, (4 * $s), (3 * $s), (12 * $s), (14 * $s))
            $g.DrawLine($pen, (7 * $s), (7 * $s), (13 * $s), (7 * $s))
            $g.DrawLine($pen, (7 * $s), (10 * $s), (13 * $s), (10 * $s))
            $g.DrawLine($pen, (7 * $s), (13 * $s), (11 * $s), (13 * $s))
        }
        # An arrow curling back on itself: fetch the newer version.
        "update" {
            $g.DrawArc($pen, (3.5 * $s), (3.5 * $s), (13 * $s), (13 * $s), 40, 280)
            $g.DrawLine($pen, (16 * $s), (3 * $s), (16 * $s), (8 * $s))
            $g.DrawLine($pen, (16 * $s), (8 * $s), (11.5 * $s), (8 * $s))
        }
        # A parcel, tied: the packaged copies kept on a stick.
        "box" {
            $g.DrawRectangle($pen, (3 * $s), (6 * $s), (14 * $s), (11 * $s))
            $g.DrawLine($pen, (3 * $s), (10 * $s), (17 * $s), (10 * $s))
            $g.DrawLine($pen, (10 * $s), (6 * $s), (10 * $s), (17 * $s))
            $g.DrawLine($pen, (7 * $s), (3.5 * $s), (10 * $s), (6 * $s))
            $g.DrawLine($pen, (13 * $s), (3.5 * $s), (10 * $s), (6 * $s))
        }
        # A shield: a copy kept somewhere else.
        "backup" {
            $g.DrawLine($pen, (10 * $s), (2.5 * $s), (4 * $s), (5 * $s))
            $g.DrawLine($pen, (10 * $s), (2.5 * $s), (16 * $s), (5 * $s))
            $g.DrawLine($pen, (4 * $s), (5 * $s), (4 * $s), (10 * $s))
            $g.DrawLine($pen, (16 * $s), (5 * $s), (16 * $s), (10 * $s))
            $g.DrawArc($pen, (4 * $s), (2 * $s), (12 * $s), (16 * $s), 20, 140)
            $g.DrawLine($pen, (7.5 * $s), (9.5 * $s), (9.3 * $s), (11.3 * $s))
            $g.DrawLine($pen, (9.3 * $s), (11.3 * $s), (12.8 * $s), (7.5 * $s))
        }
        # An arrow onto a baseline: put it on the desktop.
        "pin" {
            $g.DrawLine($pen, (10 * $s), (3 * $s), (10 * $s), (12 * $s))
            $g.DrawLine($pen, (6 * $s), (8.5 * $s), (10 * $s), (12.5 * $s))
            $g.DrawLine($pen, (14 * $s), (8.5 * $s), (10 * $s), (12.5 * $s))
            $g.DrawLine($pen, (4 * $s), (16 * $s), (16 * $s), (16 * $s))
        }
        # The Stratum mark: three strata cut by two section lines.
        "mark" {
            $g.DrawLine($pen, (2 * $s), (6 * $s), (18 * $s), (6 * $s))
            $g.DrawLine($pen, (2 * $s), (10 * $s), (18 * $s), (10 * $s))
            $g.DrawLine($pen, (2 * $s), (14 * $s), (18 * $s), (14 * $s))
            $faint = New-Object System.Drawing.Pen $Colour, 1.0
            $g.DrawLine($faint, (7 * $s), (2 * $s), (7 * $s), (18 * $s))
            $g.DrawLine($faint, (13 * $s), (2 * $s), (13 * $s), (18 * $s))
            $faint.Dispose()
        }
    }

    $pen.Dispose()
    $brush.Dispose()
    $g.Dispose()
    return $bitmap
}

# The window's own icon, built from the mark and cached beside the project so
# a desktop shortcut has something to point at.
function Get-AppIcon {
    $iconPath = Join-Path $Root ".stratum-icon.ico"
    $bitmap = New-Object System.Drawing.Bitmap 64, 64
    $g = [System.Drawing.Graphics]::FromImage($bitmap)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear($Bone)
    $mark = New-Glyph -Name "mark" -Size 52 -Colour $Clay
    $g.DrawImage($mark, 6, 6)
    $mark.Dispose()
    $g.Dispose()

    $handle = $bitmap.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($handle)
    try {
        $stream = [System.IO.File]::Create($iconPath)
        $icon.Save($stream)
        $stream.Close()
    } catch {
        # A read-only folder is not a reason to refuse to open the window.
    }
    return @{ Icon = $icon; Path = $iconPath }
}

# --------------------------------------------------------------------------
# Running the real scripts
#
# Each button opens the console script that already exists rather than
# reimplementing it here. Those scripts explain themselves as they go - which
# is most of their value when something goes wrong - and a window that
# swallowed their output to look tidier would be a worse launcher, not a
# better one.
# --------------------------------------------------------------------------
function Invoke-Script([string]$Name, [switch]$Wait) {
    $path = Join-Path $PSScriptRoot $Name
    if (-not (Test-Path $path)) {
        [System.Windows.Forms.MessageBox]::Show(
            "The file $Name is missing from the scripts folder. Use Update to fetch the project again.",
            "Stratum", "OK", "Warning") | Out-Null
        return
    }
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $path)
    if ($Wait) {
        Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Wait
    } else {
        Start-Process -FilePath "powershell.exe" -ArgumentList $arguments
    }
}

# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------
$app = Get-AppIcon

$form = New-Object System.Windows.Forms.Form
$form.Text = "Stratum"
$form.Size = New-Object System.Drawing.Size 560, 620
$form.MinimumSize = New-Object System.Drawing.Size 480, 560
$form.StartPosition = "CenterScreen"
$form.BackColor = $Bone
$form.Font = $FontUi
$form.Icon = $app.Icon

# The four bands of the window, in order, top to bottom. Sized in rows rather
# than docked: docking order is the reverse of the order controls are added,
# which is a rule nobody remembers and which silently stacks a window upside
# down when it is got wrong.
$layout = New-Object System.Windows.Forms.TableLayoutPanel
$layout.Dock = "Fill"
$layout.ColumnCount = 1
$layout.RowCount = 4
$layout.BackColor = $Bone
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle ([System.Windows.Forms.SizeType]::Absolute), 78))
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle ([System.Windows.Forms.SizeType]::Absolute), 1))
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle ([System.Windows.Forms.SizeType]::Absolute), 62))
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle ([System.Windows.Forms.SizeType]::Percent), 100))
$form.Controls.Add($layout)

# ------------------------------------------------------------------ header
$header = New-Object System.Windows.Forms.Panel
$header.Dock = "Fill"
$header.Margin = New-Object System.Windows.Forms.Padding 0
$header.BackColor = $Surface
$layout.Controls.Add($header, 0, 0)

$logo = New-Object System.Windows.Forms.PictureBox
$logo.Image = New-Glyph -Name "mark" -Size 34 -Colour $Clay
$logo.SizeMode = "AutoSize"
$logo.Location = New-Object System.Drawing.Point 22, 22
$header.Controls.Add($logo)

$title = New-Object System.Windows.Forms.Label
$title.Text = "Stratum"
$title.Font = $FontTitle
$title.ForeColor = $Ink
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point 66, 18
$header.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Research and collections platform - version $Version"
$subtitle.Font = $FontSmall
$subtitle.ForeColor = $Ink2
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point 68, 48
$header.Controls.Add($subtitle)

$rule = New-Object System.Windows.Forms.Panel
$rule.Dock = "Fill"
$rule.Margin = New-Object System.Windows.Forms.Padding 0
$rule.BackColor = $Border
$layout.Controls.Add($rule, 0, 1)

# ------------------------------------------------------------------ status
$statusPanel = New-Object System.Windows.Forms.Panel
$statusPanel.Dock = "Fill"
$statusPanel.Margin = New-Object System.Windows.Forms.Padding 0
$statusPanel.BackColor = $Bone
$layout.Controls.Add($statusPanel, 0, 2)

$dot = New-Object System.Windows.Forms.Panel
$dot.Size = New-Object System.Drawing.Size 12, 12
$dot.Location = New-Object System.Drawing.Point 24, 25
$dot.BackColor = $Ink2
$statusPanel.Controls.Add($dot)

$statusText = New-Object System.Windows.Forms.Label
$statusText.Text = "Checking..."
$statusText.Font = $FontStrong
$statusText.ForeColor = $Ink
$statusText.AutoSize = $true
$statusText.Location = New-Object System.Drawing.Point 46, 22
$statusPanel.Controls.Add($statusText)

$statusNote = New-Object System.Windows.Forms.Label
$statusNote.Text = ""
$statusNote.Font = $FontSmall
$statusNote.ForeColor = $Ink2
$statusNote.AutoSize = $true
$statusNote.Location = New-Object System.Drawing.Point 46, 40
$statusPanel.Controls.Add($statusNote)

# --------------------------------------------------------------- the buttons
$body = New-Object System.Windows.Forms.FlowLayoutPanel
$body.Dock = "Fill"
$body.FlowDirection = "TopDown"
$body.WrapContents = $false
$body.AutoScroll = $true
$body.Padding = New-Object System.Windows.Forms.Padding 20, 6, 20, 20
$body.Margin = New-Object System.Windows.Forms.Padding 0
$body.BackColor = $Bone
$layout.Controls.Add($body, 0, 3)

function New-Heading([string]$Text) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text.ToUpper()
    $label.Font = $FontSmall
    $label.ForeColor = $Ink2
    $label.AutoSize = $true
    $label.Margin = New-Object System.Windows.Forms.Padding 2, 14, 0, 6
    return $label
}

function New-Action {
    param(
        [string]$Label,
        [string]$Note,
        [string]$Glyph,
        [scriptblock]$OnClick,
        [switch]$Primary
    )

    $button = New-Object System.Windows.Forms.Button
    $button.Width = 480
    $button.Height = 52
    $button.Margin = New-Object System.Windows.Forms.Padding 0, 0, 0, 8
    $button.FlatStyle = "Flat"
    $button.TextAlign = "MiddleLeft"
    $button.ImageAlign = "MiddleLeft"
    $button.TextImageRelation = "ImageBeforeText"
    $button.Padding = New-Object System.Windows.Forms.Padding 14, 0, 0, 0
    $button.Cursor = [System.Windows.Forms.Cursors]::Hand
    $button.Add_Click($OnClick)

    if ($Primary) {
        $button.BackColor = $Clay
        $button.ForeColor = [System.Drawing.Color]::White
        $button.FlatAppearance.BorderSize = 0
        $button.FlatAppearance.MouseOverBackColor = $ClayDark
        $button.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 11)
        $button.Image = New-Glyph -Name $Glyph -Size 22 -Colour ([System.Drawing.Color]::White)
        $button.Text = "   $Label"
    } else {
        $button.BackColor = $Surface
        $button.ForeColor = $Ink
        $button.FlatAppearance.BorderColor = $Border
        $button.FlatAppearance.BorderSize = 1
        $button.FlatAppearance.MouseOverBackColor = [System.Drawing.Color]::FromArgb(238, 232, 221)
        $button.Font = $FontUi
        $button.Image = New-Glyph -Name $Glyph -Size 20 -Colour $Bronze
        # Two lines: what it does, then what that means. The second line is
        # why nobody has to remember which file was which.
        $button.Text = "   $Label`n   $Note"
    }
    return $button
}

# The one button whose meaning changes with the state of the platform.
$mainButton = New-Action -Label "Start Stratum" -Glyph "start" -Primary -Note "" -OnClick {
    if ($script:Running) {
        Invoke-Script "stop.ps1"
    } else {
        Invoke-Script "start.ps1"
    }
}
$body.Controls.Add($mainButton)

$openButton = New-Action -Label "Open Stratum" -Note "Show it in the browser" -Glyph "open" -OnClick {
    Start-Process "http://localhost:5173"
}
$body.Controls.Add($openButton)

$body.Controls.Add((New-Heading "Bringing things in"))

$body.Controls.Add((New-Action -Label "Add photographs" -Note "Send a folder of pictures into a record" -Glyph "photos" -OnClick {
    Invoke-Script "photos.ps1"
}))

$body.Controls.Add((New-Action -Label "Where the files are kept" -Note "Put photographs and the database on another disk" -Glyph "disk" -OnClick {
    Invoke-Script "datafolder.ps1"
}))

$body.Controls.Add((New-Heading "Sharing and checking"))

$body.Controls.Add((New-Action -Label "Share on the office network" -Note "Let other computers here open it" -Glyph "wifi" -OnClick {
    Invoke-Script "share.ps1"
}))

$body.Controls.Add((New-Action -Label "Check e-mail sending" -Note "Send yourself a test message" -Glyph "mail" -OnClick {
    Invoke-Script "checkemail.ps1"
}))

$body.Controls.Add((New-Action -Label "Show the log" -Note "What happened, safe to send on for help" -Glyph "log" -OnClick {
    Invoke-Script "logs.ps1"
}))

$body.Controls.Add((New-Heading "Keeping it safe"))

$body.Controls.Add((New-Action -Label "Back everything up" -Note "Records and files, to a stick or another disk" -Glyph "backup" -OnClick {
    Invoke-Script "backup.ps1"
}))

$body.Controls.Add((New-Heading "Keeping it current"))

$body.Controls.Add((New-Action -Label "Update to the newest version" -Note "Fetch changes, then rebuild" -Glyph "update" -OnClick {
    Invoke-Script "update.ps1"
}))

$body.Controls.Add((New-Action -Label "Save the offline copies" -Note "Installers for Docker and Node, to keep on a stick" -Glyph "box" -OnClick {
    Invoke-Script "extract-apps.ps1"
}))

$body.Controls.Add((New-Action -Label "Put Stratum on the desktop" -Note "A shortcut with its own icon" -Glyph "pin" -OnClick {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut((Join-Path $desktop "Stratum.lnk"))
        $link.TargetPath = Join-Path $Root "Stratum.cmd"
        $link.WorkingDirectory = $Root
        $link.Description = "Open the Stratum platform"
        if (Test-Path $app.Path) { $link.IconLocation = $app.Path }
        $link.Save()
        [System.Windows.Forms.MessageBox]::Show(
            "Stratum is on your desktop.", "Stratum", "OK", "Information") | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show(
            "The shortcut could not be made: $($_.Exception.Message)",
            "Stratum", "OK", "Warning") | Out-Null
    }
}))

# --------------------------------------------------------------------------
# Is it running?
#
# Asked of the backend and the website separately, because they fail
# separately and the answer changes what to do about it. Both are checked with
# a short timeout on a background-friendly call, so a stopped platform costs a
# fraction of a second rather than freezing the window.
# --------------------------------------------------------------------------
$script:Running = $false

function Test-Endpoint([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Update-Status {
    $api = Test-Endpoint "http://localhost:8000/api/v1/health"
    $web = Test-Endpoint "http://localhost:5173"

    if ($api -and $web) {
        $script:Running = $true
        $dot.BackColor = $Bronze
        $statusText.Text = "Running"
        $statusText.ForeColor = $Ink
        $statusNote.Text = "Open it at http://localhost:5173"
        $mainButton.Text = "   Stop Stratum"
        $mainButton.Image = New-Glyph -Name "stop" -Size 22 -Colour ([System.Drawing.Color]::White)
        $openButton.Enabled = $true
    } elseif ($api) {
        # A real and common state: the backend is up in Docker but the window
        # running the website was closed. Naming it saves somebody restarting
        # everything to fix half of it.
        $script:Running = $false
        $dot.BackColor = $Amber
        $statusText.Text = "Half running"
        $statusText.ForeColor = $Ink
        $statusNote.Text = "The backend is up; the website is not. Press Start."
        $mainButton.Text = "   Start Stratum"
        $mainButton.Image = New-Glyph -Name "start" -Size 22 -Colour ([System.Drawing.Color]::White)
        $openButton.Enabled = $false
    } else {
        $script:Running = $false
        $dot.BackColor = $Ink2
        $statusText.Text = "Stopped"
        $statusText.ForeColor = $Ink
        $statusNote.Text = "Press Start. The first run after an update takes a few minutes."
        $mainButton.Text = "   Start Stratum"
        $mainButton.Image = New-Glyph -Name "start" -Size 22 -Colour ([System.Drawing.Color]::White)
        $openButton.Enabled = $false
    }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 3000
$timer.Add_Tick({ Update-Status })
$timer.Start()

$form.Add_Shown({ Update-Status })
$form.Add_FormClosed({ $timer.Stop() })

[void]$form.ShowDialog()
