@echo off
REM Double-click this when something did not start, or stopped working.
REM
REM It shows what the platform itself said - the part that names the actual
REM problem. Nothing here changes anything; it only reads and prints.
REM
REM It also writes the same text to "stratum-log.txt" next to this file, so
REM the whole thing can be attached to a message rather than retyped.

title Stratum - log
cd /d "%~dp0.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\logs.ps1"

pause
