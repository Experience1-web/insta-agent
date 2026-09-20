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
echo   Trag die Zahl hier ein. Punkt statt Komma: 1.11
echo.
echo   Leer lassen zeigt nur den Stand.
echo   Ein s richtet ein, dass er selbst nachrechnet.
echo.
set /p BETRAG=Guthaben in USD: 
if /i "%BETRAG%"=="s" goto schluessel
if "%BETRAG%"=="" goto zeigen
%PY% -m insta_agent.cli kasse %BETRAG%
echo.
pause
exit /b
:zeigen
%PY% -m insta_agent.cli kasse
echo.
pause
exit /b
:schluessel
%PY% -m insta_agent.cli kasse --schluessel
echo.
pause
