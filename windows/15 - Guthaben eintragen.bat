@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Guthaben eintragen
echo.
echo   Der Agent schaetzt seine Kosten selbst. Die Wahrheit steht auf
echo   console.anthropic.com unter "Organisations-Credits".
echo.
echo   Trag die Zahl hier ein, damit er seine Grenzen auf echten
echo   Zahlen zieht. Punkt statt Komma: 1.11
echo.
set /p BETRAG=Guthaben in USD (leer lassen zeigt nur den Stand): 
if "%BETRAG%"=="" goto zeigen
%PY% -m insta_agent.cli kasse %BETRAG%
echo.
pause
exit /b
:zeigen
%PY% -m insta_agent.cli kasse
echo.
pause
