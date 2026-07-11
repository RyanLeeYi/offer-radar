@echo off
REM Double-click to stop offer-radar (API + Bot). Ollama is left running.
where pwsh >nul 2>nul
if %errorlevel%==0 (set "PS=pwsh") else (set "PS=powershell")
%PS% -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'api\.main:app|bot\.main' } | ForEach-Object { taskkill /PID $_.ProcessId /T /F } | Out-Null; 'offer-radar stopped (Ollama left running).'"
echo.
pause
