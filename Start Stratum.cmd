@echo off
REM Double-click this file to start the platform.
REM
REM It exists because Windows opens a .ps1 file in Notepad rather than running
REM it - a security default worth keeping - so this asks PowerShell to run the
REM real script next door.
REM
REM -ExecutionPolicy Bypass applies to this one run only. It does not change
REM any setting on the computer.

title Stratum
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"

REM If PowerShell itself could not start, the window would vanish before the
REM reason could be read. Hold it open.
if errorlevel 1 (
    echo.
    echo The launcher stopped. The messages above say why.
    pause
)
