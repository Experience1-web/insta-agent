@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Neue Version holen
git pull
echo.
%PY% -m pip install -e . --quiet
echo   Fertig.
echo.
pause
