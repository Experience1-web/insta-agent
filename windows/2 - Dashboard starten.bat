@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title insta-agent - dieses Fenster offen lassen
set PY=py
where py >nul 2>&1
if errorlevel 1 set PY=python
%PY% -m insta_agent.cli web
echo.
echo   Das Dashboard wurde beendet.
pause
