@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title insta-agent - dieses Fenster offen lassen
echo.
echo   Gleich erscheint ein QR-Code fuers Handy.
echo.
%PY% -m insta_agent.cli web --host 0.0.0.0 --read-only
echo.
pause
