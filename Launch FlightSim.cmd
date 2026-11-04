@echo off
rem Double-click launcher (Phase 3 E6): runs scripts\launch_windows.ps1 from this folder.
rem No pause, no prompt; on a failure the window stays open (cmd /k) so the
rem FAILED line can be read. logs\launch.log keeps every line.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\launch_windows.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" cmd /k
exit /b %RC%
