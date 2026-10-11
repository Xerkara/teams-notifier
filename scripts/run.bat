@echo off
rem teams-notifier'ı elle calistirir (cift tikla). Sonucu gosterip bekler.
chcp 65001 >nul
set "ROOT=%~dp0.."
"%ROOT%\.venv\Scripts\python.exe" -m teams_notifier run
echo.
pause
