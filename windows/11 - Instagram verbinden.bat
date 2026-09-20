@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Instagram verbinden
echo.
echo   Damit der Agent selbst posten kann.
echo.
echo   Du brauchst drei Angaben von developers.facebook.com.
echo   Welche genau, steht gleich auf dem Bildschirm.
echo.
%PY% -m insta_agent.cli instagram
echo.
pause
