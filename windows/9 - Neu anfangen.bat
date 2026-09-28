@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Neu anfangen
echo.
echo   Der Agent sucht sich eine neue Nische, einen neuen Namen
echo   und eine neue Strategie.
echo.
echo   Seine Kasse, sein Arbeitsprotokoll und die schon geschriebenen
echo   Beiträge bleiben erhalten.
echo.
echo   Gleich kommt eine Rückfrage. Tippe  j  und drücke Enter.
echo   ^(y geht auch^). Wenn du es dir anders überlegst: n und Enter.
echo.
%PY% -m insta_agent.cli neustart
echo.
echo   Danach: Doppelklick auf  2 - Dashboard starten
echo   und dort auf  Starten  drücken.
echo.
pause
