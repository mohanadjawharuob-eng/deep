@echo off
REM Double-click this to shut everything down (or press Stop in the Stratum
REM window, which does exactly the same thing).
REM
REM Closing the Start Stratum window stops the website, but the database and
REM the API keep running in Docker - which is usually what you want, and
REM occasionally not.
REM
REM Your data is kept. This stops the programs; it deletes nothing.

title Stratum - stopping
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"

if errorlevel 1 (
    echo.
    echo The stop script could not run. The messages above say why.
    pause
)
