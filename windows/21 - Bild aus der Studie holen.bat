@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Bild aus der Studie holen
echo.
echo   Holt Bilder vom Fund selbst - aus der Originalstudie oder von
echo   einer Behörde wie der NASA. Kostet nichts.
echo.
echo   Funktioniert mit Seiten von PLOS, Frontiers, MDPI, Pensoft (ZooKeys),
echo   eLife, PeerJ, Scientific Reports, Nature Communications, NASA, NOAA,
echo   USGS. Nachrichtenseiten gehen nicht - deren Bilder gehören Agenturen.
echo.
echo   Tipp: Die Adresse steht im Dashboard beim Fund unter "Quellen".
echo.
set /p ADRESSE=Adresse der Seite einfügen (Rechtsklick fügt ein): 
echo.
%PY% -m insta_agent.cli quellprobe "%ADRESSE%"
echo.
pause
