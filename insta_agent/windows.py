"""Windows-Autostart: das Dashboard soll nach dem Anmelden von selbst da sein.

Dafür legt Windows alles ab, was im Autostart-Ordner des Benutzers liegt.
Eine kleine Startdatei dort genügt - kein Dienst, keine Registry, nichts,
was man später nicht einfach wieder löschen könnte.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import REPO_ROOT

DATEINAME = "insta-agent-dashboard.bat"


def autostart_ordner() -> Path | None:
    """Der Autostart-Ordner des angemeldeten Benutzers, falls es ihn gibt."""
    appdata = os.getenv("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _ziel() -> Path | None:
    ordner = autostart_ordner()
    return ordner / DATEINAME if ordner else None


@dataclass(slots=True)
class Ergebnis:
    erfolg: bool
    nachricht: str
    pfad: Path | None = None


def ist_eingeschaltet() -> bool:
    ziel = _ziel()
    return bool(ziel and ziel.exists())


def einschalten(*, host: str = "127.0.0.1", port: int = 8765, nur_lesen: bool = False) -> Ergebnis:
    """Legt die Startdatei im Autostart-Ordner ab."""
    ziel = _ziel()
    if ziel is None:
        return Ergebnis(False, "Kein Autostart-Ordner gefunden - das gibt es nur unter Windows.")

    befehl = f'%PY% -m insta_agent.cli web --host {host} --port {port} --no-open'
    if nur_lesen:
        befehl += " --read-only"

    # chcp 65001 stellt die Ausgabe auf UTF-8 um, sonst werden Umlaute
    # im schwarzen Fenster zu Fragezeichen.
    inhalt = "\r\n".join(
        [
            "@echo off",
            "chcp 65001 >nul",
            f'cd /d "{REPO_ROOT}"',
            "set PY=py",
            "where py >nul 2>&1",
            "if errorlevel 1 set PY=python",
            "title insta-agent - dieses Fenster offen lassen",
            befehl,
            "pause",
            "",
        ]
    )

    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(inhalt, encoding="utf-8")
    except OSError as exc:
        return Ergebnis(False, f"Konnte die Startdatei nicht anlegen: {exc}")

    return Ergebnis(True, "Das Dashboard startet ab jetzt beim Anmelden mit.", ziel)


def ausschalten() -> Ergebnis:
    ziel = _ziel()
    if ziel is None:
        return Ergebnis(False, "Kein Autostart-Ordner gefunden - das gibt es nur unter Windows.")
    if not ziel.exists():
        return Ergebnis(True, "Der Autostart war gar nicht eingeschaltet.")

    try:
        ziel.unlink()
    except OSError as exc:
        return Ergebnis(False, f"Konnte die Startdatei nicht entfernen: {exc}")

    return Ergebnis(True, "Das Dashboard startet nicht mehr automatisch mit.", ziel)
