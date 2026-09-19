@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title insta-agent einrichten
set PY=py
where py >nul 2>&1
if errorlevel 1 set PY=python
echo.
echo   Schritt 1 von 2: Programm installieren
echo.
%PY% -m pip install -e . --quiet
if errorlevel 1 goto fehler
echo.
echo   Schritt 2 von 2: API-Schluessel eintragen
echo.
%PY% -m insta_agent.cli setup
echo.
pause
exit /b
:fehler
echo.
echo   Die Installation ist fehlgeschlagen.
echo   Ist Python installiert? Teste es mit:  py --version
echo.
pause
