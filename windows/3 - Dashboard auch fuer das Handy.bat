@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title insta-agent - dieses Fenster offen lassen
set PY=py
where py >/dev/null 2>&1
if errorlevel 1 set PY=python
%PY% -m insta_agent.cli stopp >/dev/null 2>&1
echo.
echo   Gleich erscheint ein QR-Code fuers Handy.
echo.
%PY% -m insta_agent.cli web --host 0.0.0.0 --read-only
echo.
pause
