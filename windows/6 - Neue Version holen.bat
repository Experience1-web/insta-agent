@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Neue Version holen
echo.
echo   Hole die neue Version ...
echo.
rem Hart auf den Stand des Servers setzen. Ein einfaches "git pull"
rem scheitert, sobald Git eine Datei fuer bearbeitet haelt - etwa wegen
rem umgewandelter Zeilenenden. Eigene Dateien (.env, state, out) sind
rem von Git ausgenommen und bleiben erhalten.
git fetch origin
if errorlevel 1 goto netzfehler
for /f "tokens=*" %%b in ('git rev-parse --abbrev-ref HEAD') do set ZWEIG=%%b
git reset --hard origin/%ZWEIG%
if errorlevel 1 goto gitfehler
echo.
%PY% -m pip install -e . --quiet
echo.
echo   Fertig. Jetzt auf diesem Stand:
git log -1 --format="   %%h vom %%cd" --date=format:"%%d.%%m. %%H:%%M"
echo.
pause
exit /b
:netzfehler
echo.
echo   Keine Verbindung zu GitHub. Internet pruefen und nochmal versuchen.
echo.
pause
exit /b
:gitfehler
echo.
echo   Die Aktualisierung ist fehlgeschlagen. Zeig mir diesen Text.
echo.
pause
