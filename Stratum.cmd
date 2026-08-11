@echo off
REM ===========================================================================
REM  Stratum
REM
REM  Double-click this. It is the only file in this folder you need.
REM
REM  It opens the Stratum window: start and stop the platform, add
REM  photographs, share it on the office network, check e-mail, update to the
REM  newest version. Everything that used to be a separate .cmd file is a
REM  button in there. Those files still exist, in the "tools" folder, for
REM  anyone who prefers them.
REM
REM  It exists as a .cmd because Windows opens a .ps1 file in Notepad rather
REM  than running it - a security default worth keeping - so this asks
REM  PowerShell to run the real script next door.
REM
REM  -ExecutionPolicy Bypass applies to this one run only. It changes no
REM  setting on the computer.
REM
REM  "start /b" so this black console window closes the moment the Stratum
REM  window opens, instead of sitting behind it for the rest of the session.
REM  If PowerShell cannot start at all, scripts\app.ps1 writes the reason to
REM  stratum-launcher-error.txt beside this file and says so.
REM ===========================================================================

cd /d "%~dp0"

start "" /b powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\app.ps1"
