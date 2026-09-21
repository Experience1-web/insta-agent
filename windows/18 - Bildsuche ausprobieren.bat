@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Bildsuche ausprobieren
echo.
echo   Sucht eine echte, frei nutzbare Aufnahme - und kostet nichts.
echo.
echo   Hier wird kein Modell gefragt. Es laeuft nur die Bildsuche:
echo   Wikimedia Commons, dann Openverse, Lizenzpruefung, Herunterladen.
echo.
echo   Gedacht zum Ausprobieren: Findet die Suche zu deinem Thema
echo   ueberhaupt etwas? Traegt Englisch besser als Deutsch?
echo.
set /p WORT=Wonach suchen (englisch bringt mehr Treffer): 
echo.
%PY% -m insta_agent.cli bildsuche "%WORT%" --alle
echo.
pause
