@echo off
REM Double-click this to bring a folder of photographs into the platform.
REM
REM Arrange the folder like this and it works out where each photograph goes:
REM
REM   <the folder you choose>
REM     TED-A                 <- a site code, exactly as recorded
REM       1001                <- a context number on that site
REM         IMG_0001.jpg
REM       IMG_0100.jpg        <- straight on the site, no context
REM     TED-B
REM       ...
REM
REM A folder whose name matches nothing is reported and skipped, never guessed
REM at. It shows you the counts and waits before uploading anything, and it
REM remembers what it has already sent - so run it again after a day's
REM photography and only the new ones go up.

title Stratum - add photographs
cd /d "%~dp0.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\photos.ps1"

pause
