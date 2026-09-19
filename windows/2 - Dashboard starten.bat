@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title insta-agent - dieses Fenster offen lassen
%PY% -m insta_agent.cli web
echo.
echo   Das Dashboard wurde beendet.
pause
