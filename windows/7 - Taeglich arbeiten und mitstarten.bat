@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
echo.
echo   Ab jetzt startet das Dashboard beim Hochfahren von selbst,
echo   ist im WLAN erreichbar und der Agent arbeitet einmal taeglich.
echo.
%PY% -m insta_agent.cli autostart --ein --handy --arbeitet 24
echo.
pause
