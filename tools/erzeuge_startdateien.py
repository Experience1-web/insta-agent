"""Erzeugt die Windows-Startdateien im Ordner `windows/`.

Warum ein Skript und nicht von Hand: Beim Schreiben über eine Unix-Shell
wurde `>nul` an manchen Stellen still zu `>/dev/null` umgeschrieben. Auf
Windows ist das ein ungültiger Pfad, und die Datei meldete beim Doppelklick
"Pfad nicht gefunden" - ohne dass man der Datei ansah, warum.

Hier entsteht der Inhalt in Python, und `pruefe()` sieht anschließend nach,
dass keine Unix-Schreibweise hineingeraten ist.
"""

from __future__ import annotations

import sys
from pathlib import Path

ZIEL = Path(__file__).resolve().parent.parent / "windows"

# Jede Datei beginnt gleich: Ausgabe auf UTF-8 (sonst werden Umlaute zu
# Fragezeichen), ins Projektverzeichnis wechseln, Python finden.
KOPF = """@echo off
chcp 65001 > nul
cd /d "%~dp0.."
set PY=py
where py > nul 2> nul
if errorlevel 1 set PY=python"""

DATEIEN: dict[str, str] = {
    "1 - Einrichten.bat": f"""{KOPF}
title insta-agent einrichten
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
pause""",
    "2 - Dashboard starten.bat": f"""{KOPF}
title insta-agent - dieses Fenster offen lassen
%PY% -m insta_agent.cli web
echo.
echo   Das Dashboard wurde beendet.
pause""",
    "3 - Dashboard auch fuer das Handy.bat": f"""{KOPF}
title insta-agent - dieses Fenster offen lassen
echo.
echo   Gleich erscheint ein QR-Code fuers Handy.
echo.
%PY% -m insta_agent.cli web --host 0.0.0.0 --read-only
echo.
pause""",
    "4 - Beim Hochfahren mitstarten.bat": f"""{KOPF}
%PY% -m insta_agent.cli autostart --ein --handy
echo.
pause""",
    "5 - Nicht mehr mitstarten.bat": f"""{KOPF}
%PY% -m insta_agent.cli autostart --aus
echo.
pause""",
    "6 - Neue Version holen.bat": f"""{KOPF}
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
pause""",
    "7 - Taeglich arbeiten und mitstarten.bat": f"""{KOPF}
echo.
echo   Ab jetzt startet das Dashboard beim Hochfahren von selbst,
echo   ist im WLAN erreichbar und der Agent arbeitet einmal taeglich.
echo.
%PY% -m insta_agent.cli autostart --ein --handy --arbeitet 24
echo.
pause""",
    "16 - Instagram-Rechte pruefen.bat": f"""{KOPF}
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
pause""",
    "15 - Guthaben eintragen.bat": f"""{KOPF}
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
pause""",
    "14 - Jetzt posten.bat": f"""{KOPF}
title Jetzt posten
echo.
echo   Schickt raus, was du schon freigegeben hast.
echo.
echo   Kostet kein Guthaben - es wird nichts gedacht,
echo   nur hochgeladen.
echo.
%PY% -m insta_agent.cli posten
echo.
pause""",
    "13 - Wirklich veroeffentlichen.bat": f"""{KOPF}
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
pause""",
    "12 - Platz fuer die Bilder.bat": f"""{KOPF}
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
pause""",
    "11 - Instagram verbinden.bat": f"""{KOPF}
title Instagram verbinden
echo.
echo   Damit der Agent selbst posten kann.
echo.
echo   Du brauchst drei Angaben von developers.facebook.com.
echo   Welche genau, steht gleich auf dem Bildschirm.
echo.
%PY% -m insta_agent.cli instagram
echo.
pause""",
    "10 - Bilder einrichten.bat": f"""{KOPF}
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
pause""",
    "9 - Neu anfangen.bat": f"""{KOPF}
title Neu anfangen
echo.
echo   Der Agent sucht sich eine neue Nische, einen neuen Namen
echo   und eine neue Strategie.
echo.
echo   Seine Kasse, sein Arbeitsprotokoll und die schon geschriebenen
echo   Beitraege bleiben erhalten.
echo.
echo   Gleich kommt eine Rueckfrage. Tippe  j  und druecke Enter.
echo   ^(y geht auch^). Wenn du es dir anders ueberlegst: n und Enter.
echo.
%PY% -m insta_agent.cli neustart
echo.
echo   Danach: Doppelklick auf  2 - Dashboard starten
echo   und dort auf  Starten  druecken.
echo.
pause""",
    "8 - Dashboard beenden.bat": f"""{KOPF}
echo.
echo   Beendet ein laufendes Dashboard, dessen Fenster nicht auffindbar ist.
echo.
%PY% -m insta_agent.cli stopp
echo.
pause""",
}


def schreibe() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    for name, inhalt in DATEIEN.items():
        # Zeilenenden im Windows-Stil, sonst stolpert die Eingabeaufforderung.
        (ZIEL / name).write_bytes((inhalt + "\n").replace("\n", "\r\n").encode("utf-8"))


def pruefe() -> list[str]:
    """Sucht nach allem, was auf Windows nicht funktioniert."""
    fehler: list[str] = []
    for name in DATEIEN:
        datei = ZIEL / name
        if not datei.exists():
            fehler.append(f"{name}: fehlt")
            continue

        roh = datei.read_bytes()
        inhalt = roh.decode("utf-8")

        if b"\r\n" not in roh:
            fehler.append(f"{name}: keine Windows-Zeilenenden")
        if "/dev/null" in inhalt:
            fehler.append(f"{name}: enthält /dev/null statt nul")
        for unix in (" && ", " || ", "$(", "#!/"):
            if unix in inhalt:
                fehler.append(f"{name}: enthält Unix-Schreibweise {unix!r}")
        if not inhalt.startswith("@echo off"):
            fehler.append(f"{name}: beginnt nicht mit @echo off")
        if "chcp 65001" not in inhalt:
            fehler.append(f"{name}: ohne chcp werden Umlaute zu Fragezeichen")

    return fehler


if __name__ == "__main__":
    schreibe()
    probleme = pruefe()
    for p in probleme:
        print(f"FEHLER  {p}")
    if probleme:
        sys.exit(1)
    print(f"{len(DATEIEN)} Startdateien geschrieben und geprüft.")
