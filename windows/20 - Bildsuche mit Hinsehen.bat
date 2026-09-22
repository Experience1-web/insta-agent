@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Bildsuche mit Hinsehen
echo.
echo   Dieselbe Bildsuche wie bei 18 - aber jedes gefundene Bild wird
echo   kurz angesehen, bevor entschieden wird.
echo.
echo   Das ist das Einzige, was beantworten kann, ob ein Bild die Sache
echo   zeigt, um die es geht. Alles andere - Name, Größe, Schärfe -
echo   steht neben dem Bild und nicht darin.
echo.
echo   Kostet rund 0,05 Cent je Bild. Bei vier Bildern also ungefähr
echo   ein Fünftel Cent für den ganzen Versuch.
echo.
set /p WORT=Wonach suchen (englisch bringt mehr Treffer): 
echo.
%PY% -m insta_agent.cli bildsuche "%WORT%" --ansehen
echo.
pause
