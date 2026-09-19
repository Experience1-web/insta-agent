@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
%PY% -m insta_agent.cli autostart --ein --handy
echo.
pause
