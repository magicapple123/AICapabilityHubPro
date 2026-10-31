@echo off
rem AICapabilityHub Pro - start local stack. Double-click friendly wrapper.
rem Pass -Check to print the resolved paths without starting anything.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-pro-stack.ps1" %*
echo.
pause
