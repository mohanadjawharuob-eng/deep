@echo off
REM Double-click this after putting the e-mail settings in the .env file.
REM
REM It asks the running platform whether it can actually sign in to the mail
REM account, and offers to send one test message. It changes nothing, and it
REM never prints the password - only how many characters long it is - so the
REM output is safe to paste into a message.

title Stratum - e-mail check
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\checkemail.ps1"

pause
