@echo off
rem ---------------------------------------------------------------------------
rem AICapabilityHub Pro - one-click launcher for the local stack.
rem
rem This file is deliberately ASCII-only. cmd.exe parses .cmd files with the
rem current console code page, so any non-ASCII text here would be garbled
rem before "chcp" could take effect. All Chinese messages live in
rem scripts\one-click-start.ps1, which is saved as UTF-8 with BOM.
rem
rem Usage:
rem   start.cmd            full start, then open the browser
rem   start.cmd -Check     environment self-check only (starts nothing)
rem   start.cmd -NoOpen    full start without opening the browser
rem ---------------------------------------------------------------------------
setlocal

rem UTF-8 code page so the Chinese output of the PowerShell layer renders
rem correctly in this window. Done before PowerShell starts on purpose.
chcp 65001 >nul

rem %~dp0 already ends with a backslash and points at this file's folder,
rem which is also the project root. -d handles a different current drive.
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\one-click-start.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
pause

rem Propagate the real exit code: "pause" would otherwise reset it to 0 and
rem mask a failed start from any script or CI that calls start.cmd.
endlocal & exit /b %RC%
