@echo off
REM Double-click this to let everyone on the same WiFi use the platform.
REM
REM They install nothing. This prints an address; they type it into a browser.
REM Everyone shares one database.
REM
REM Use "Start Stratum.cmd" instead when you are working alone — it is quicker
REM to start and rebuilds as you change things.

title Stratum - sharing on this network
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\share.ps1"

if errorlevel 1 (
    echo.
    echo Sharing did not start. The messages above say why.
    pause
)
