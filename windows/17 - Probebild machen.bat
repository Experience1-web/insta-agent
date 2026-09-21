@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Probebild machen
echo.
echo   Malt ein einzelnes Probebild und sagt, wo es liegt.
echo.
echo   Gedacht fuer den Fall, dass im Zyklus kein Bild herauskam und
echo   man nicht weiss, woran es lag: Hier steht der Fehler im Klartext,
echo   statt im Protokoll zwischen hundert anderen Zeilen.
echo.
%PY% -m insta_agent.cli bildtest
echo.
pause
