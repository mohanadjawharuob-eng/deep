@echo off
REM Double-click this to shut the backend down.
REM
REM Closing the Start Stratum window stops the website, but the database and
REM the API keep running in Docker — which is usually what you want, and
REM occasionally not.
REM
REM Your data is kept. This stops the containers; it does not delete anything.

title Stratum - stopping
cd /d "%~dp0"

echo.
echo Stopping the backend. Your data is kept.
echo.

docker compose down

echo.
echo Stopped. Run "Start Stratum.cmd" when you want it back.
echo.
pause
