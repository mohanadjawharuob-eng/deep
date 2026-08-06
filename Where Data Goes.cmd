@echo off
REM Double-click this to choose which disk the platform keeps things on.
REM
REM A folder picker opens twice: once for the photographs and files, once for
REM the backups. Put the backups on a different drive if you have one - a backup
REM on the same disk as the thing it backs up is a copy, not a backup.
REM
REM If there are already files stored, it offers to copy them across before
REM switching. It never deletes anything.
REM
REM It also explains what to do about the database, which is a different
REM problem and is deliberately not moved by this.

title Stratum - where the data goes
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\datafolder.ps1"

pause
