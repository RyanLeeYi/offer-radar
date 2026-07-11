@echo off
REM Double-click to start offer-radar (Ollama + API + Bot).
REM Press Ctrl+C in this window to stop everything, or run stop.bat.
cd /d "%~dp0"
where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
)
echo.
pause
