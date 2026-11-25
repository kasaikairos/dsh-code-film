@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Mode interactive
if errorlevel 1 (pause & exit /b 1)
echo Setup check complete.
pause

