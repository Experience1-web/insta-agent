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
echo   Am besten die DOI der Studie, zum Beispiel:  10.1098/rsos.250890
echo   Sie steht im Dashboard beim Fund unter "Quellen". Dann kommen die
echo   Aufnahmen in voller Größe aus dem PDF - auch bei Verlagen, die
echo   Programme aussperren.
echo.
echo   Es geht auch die Adresse einer Artikelseite (PLOS, Pensoft, Frontiers)
echo   oder einer NASA-Seite. Nachrichtenseiten nicht - deren Bilder
echo   gehören Agenturen.
echo.
set /p ADRESSE=DOI oder Adresse einfügen (Rechtsklick fügt ein): 
echo.
%PY% -m insta_agent.cli quellprobe "%ADRESSE%"
echo.
pause
