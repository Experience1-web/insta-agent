@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Jetzt posten
echo.
echo   Schickt raus, was du schon freigegeben hast.
echo.
echo   Kostet kein Guthaben - es wird nichts gedacht,
echo   nur hochgeladen.
echo.
%PY% -m insta_agent.cli posten
echo.
pause
