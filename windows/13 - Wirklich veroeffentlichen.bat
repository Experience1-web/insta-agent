@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python
title Wirklich veroeffentlichen
echo.
echo   Legt den Hauptschalter um.
echo.
echo   Solange er aus ist, legt der Agent nur Entwuerfe ab - auch
echo   wenn du sie freigibst. Danach geht jede Freigabe wirklich
echo   auf Instagram.
echo.
echo   Eine Rueckfrage kommt. Tippe  j  und Enter.
echo.
%PY% -m insta_agent.cli scharf
echo.
pause
