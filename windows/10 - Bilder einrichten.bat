@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Bilder einrichten
echo.
echo   Wer soll die Bilder malen?
echo.
echo   Claude kann keine Bilder erzeugen. Du hast drei Wege:
echo   Google Gemini (kostenloses Kontingent, nur ein Schluessel),
echo   dein eigener Rechner (kostenlos, braucht eine Grafikkarte)
echo   oder Replicate (wenige Cent pro Bild, beste Qualitaet).
echo.
%PY% -m insta_agent.cli bilder
echo.
pause
