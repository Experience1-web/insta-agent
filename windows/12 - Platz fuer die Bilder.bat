@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Platz fuer die Bilder
echo.
echo   Der letzte Schritt.
echo.
echo   Instagram nimmt keine Datei entgegen - es holt sich das Bild
echo   von einer Adresse im Netz. Dafuer brauchen die fertigen
echo   Bilder einen kurzen oeffentlichen Platz.
echo.
%PY% -m insta_agent.cli ablage
echo.
pause
