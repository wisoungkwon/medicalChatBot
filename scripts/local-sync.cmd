@echo off
rem Thin ASCII wrapper. All logic and Korean messages live in local-sync.ps1.
rem Keep this file ASCII-only: cmd mis-parses multi-byte characters in .cmd files.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local-sync.ps1" -Root "%~dp0.."
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
