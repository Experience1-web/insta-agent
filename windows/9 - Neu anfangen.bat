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
echo   Beitraege bleiben erhalten.
echo.
echo   Gleich kommt eine Rueckfrage. Tippe  j  und druecke Enter.
echo   Wenn du es dir anders ueberlegst: n  und Enter.
echo.
%PY% -m insta_agent.cli neustart
echo.
echo   Danach: Doppelklick auf  2 - Dashboard starten
echo   und dort auf  Starten  druecken.
echo.
pause
