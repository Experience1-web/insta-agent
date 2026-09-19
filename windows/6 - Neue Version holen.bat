@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title Neue Version holen
git pull
echo.
set PY=py
where py >nul 2>&1
if errorlevel 1 set PY=python
%PY% -m pip install -e . --quiet
echo   Fertig.
echo.
pause
