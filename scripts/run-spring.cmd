@echo off
rem Thin ASCII wrapper. All logic and Korean messages live in run-spring.ps1.
rem Keep this file ASCII-only: cmd mis-parses multi-byte characters in .cmd files.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-spring.ps1" -Root "%~dp0.."
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
