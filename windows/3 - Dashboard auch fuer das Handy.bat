@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title insta-agent - dieses Fenster offen lassen
set PY=py
where py >nul 2>&1
if errorlevel 1 set PY=python
echo.
echo   Gleich erscheint eine zweite Adresse mit Zugangswort.
echo   Die oeffnest du einmal auf dem Handy.
echo.
%PY% -m insta_agent.cli web --host 0.0.0.0 --read-only
echo.
pause
