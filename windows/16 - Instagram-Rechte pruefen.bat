@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Instagram-Rechte pruefen
echo.
echo   Zeigt, welche Berechtigungen der hinterlegte Zugang hat.
echo.
echo   Vor allem geht es um  instagram_manage_insights  - ohne die
echo   sieht er keine Reichweite und keine Speicherungen und lernt
echo   nichts aus seinen eigenen Beitraegen.
echo.
%PY% -m insta_agent.cli rechte
echo.
pause
