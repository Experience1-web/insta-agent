@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Karussell ausprobieren
echo.
echo   Baut die Bilder des neuesten Entwurfs noch einmal - ohne Modell.
echo.
echo   Ein ganzer Zyklus waere der teuerste Weg, das Karussell zu
echo   pruefen: Stoffsuche, Text und Pruefung noch einmal bezahlt, nur
echo   um die Bilder zu sehen. Hier laeuft nur der Bildteil.
echo.
echo   Danach die Bilder nebeneinander aufmachen. Die Frage ist nicht,
echo   ob jedes fuer sich gut ist, sondern ob sie zusammen aussehen.
echo.
%PY% -m insta_agent.cli karussellprobe
echo.
pause
