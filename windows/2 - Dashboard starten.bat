@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title insta-agent - dieses Fenster offen lassen
set PY=py
where py >/dev/null 2>&1
if errorlevel 1 set PY=python
rem Ein altes Dashboard blockiert den Port; sonst startet das neue nicht
rem und der Browser zeigt weiter den alten Stand.
%PY% -m insta_agent.cli stopp >/dev/null 2>&1
%PY% -m insta_agent.cli web
echo.
echo   Das Dashboard wurde beendet.
pause
