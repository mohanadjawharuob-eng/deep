@echo off
REM Double-click this file (or use the button in the Stratum window) to lift the four offline apps out of this project.
REM
REM They were never part of the archaeology platform - they are four
REM self-contained web pages that arrived in the same folder from an earlier
REM project. This puts them in a folder of their own, next to this one, with
REM their history intact and ready to push to their own repository.
REM
REM It exists because Windows opens a .ps1 file in Notepad rather than running
REM it - a security default worth keeping - so this asks PowerShell to run the
REM real script next door.

title Extract the offline apps
cd /d "%~dp0.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\extract-apps.ps1"

if errorlevel 1 (
    echo.
    echo It stopped. The messages above say why.
    pause
)
