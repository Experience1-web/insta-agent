"""Der feste Rahmen, an dem man den Account im Feed erkennt.

Große Wissens-Accounts sehen nicht deshalb professionell aus, weil jedes
Bild anders schön ist, sondern weil jedes denselben Rahmen trägt: oben
ein kleines Etikett mit dem Gebiet, ein Seitenzähler, auf dem ersten
Bild ein Hinweis zum Wischen, und am Ende eine Karte, die immer gleich
aufgebaut ist - Frage, Quelle, Aufforderung zu folgen. Vorlagen-Seiten
verkaufen genau diesen Rahmen als Photoshop-Datei. Hier zeichnet ihn das
Programm selbst, auf jedes Bild, ohne Lizenz und ohne Modellaufruf.

Bewusst klein und zurückhaltend: Der Rahmen soll wiedererkannt werden,
nicht mit dem Hook um Aufmerksamkeit kämpfen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..models import VisualSpec
from .renderer import FEED

# Aus den Themensäulen ein Etikett, das jeder sofort versteht. "Erfunden"
# klingt auf einem Faktenaccount nach "ausgedacht" - deshalb übersetzt.
ETIKETTEN = {
    "ausgegraben": "ARCHÄOLOGIE",
    "erfunden": "FORSCHUNG",
    "lebendig": "NATUR",
    "weltall": "WELTALL",
    "kurios": "KURIOS",
}


@dataclass(frozen=True)
class Marke:
    """Was zusätzlich zum Hook auf ein Bild gehört."""

    etikett: str = ""
    # "2/6" - leer auf dem ersten Bild, dort steht der Wisch-Hinweis.
    seite: str = ""
    wischen: bool = False
    # Wie die Karte gesetzt wird - aus dem Entwurf: foto, zahl, aussage, text.
    layout: str = ""
    zahl: str = ""
    erklaerung: str = ""


def etikett_fuer(saeule: str) -> str:
    """Das Etikett zu einer Themensäule - kurz, in Großbuchstaben."""
    kopf = (saeule or "").split(":")[0].strip()
    if not kopf:
        return ""
    return ETIKETTEN.get(kopf.casefold(), kopf.upper()[:18])


# --- Die Abschlusskarte -----------------------------------------------------


def quelle_aus(caption: str) -> str:
    """Die Quellenzeile aus der Bildunterschrift - ohne "📚 Quelle:" davor."""
    for zeile in reversed((caption or "").splitlines()):
        if "Quelle" in zeile or zeile.strip().startswith("\U0001F4DA"):
            text = zeile.strip().lstrip("\U0001F4DA").strip()
            return re.sub(r"^Quellen?\s*:\s*", "", text).strip()
    return ""


def frage_aus(*texte: str) -> str:
    """Die letzte Frage aus den Texten - in dieser Reihenfolge gesucht."""
    for text in texte:
        fragen = [f.strip() for f in re.findall(r"[^.!?\n]*\?", text or "") if f.strip()]
        if fragen:
            return _nur_die_frage(fragen[-1])
    return ""


def _nur_die_frage(satz: str) -> str:
    """Ohne den Handlungsaufruf davor: "Speicher das - und sag uns: Wie ...?" wird "Wie ...?"."""
    teile = re.split(r"\s[-–—]\s", satz, maxsplit=1)
    if len(teile) == 2 and re.match(r"(Speicher|Teil|Schick|Folg|Merk)", teile[0]):
        satz = teile[1]
        if ": " in satz:
            satz = satz.split(": ", 1)[1]
        satz = re.sub(r"^(und|oder)\s+", "", satz)
    return satz[:1].upper() + satz[1:]


def render_abschlusskarte(
    spec: VisualSpec,
    ziel: Path,
    *,
    frage: str,
    quelle: str,
    handle: str,
    marke: Marke | None = None,
    groesse: tuple[int, int] = FEED,
) -> Path:
    """Die letzte Karte: die Frage groß, darunter die Quelle, unten der Account.

    Immer gleich aufgebaut - wer ein paar Beiträge gesehen hat, erkennt
    sie, bevor er sie liest. Gezeichnet vom Gestaltungssystem; `spec`
    bleibt für die Aufrufer, die ihn mitgeben.
    """
    from . import gestalt

    marke = marke or Marke()
    return gestalt.abschluss(
        ziel, frage=frage, quelle=quelle, handle=handle,
        rubrik=marke.etikett, seite=marke.seite, groesse=groesse,
    )


__all__ = [
    "Marke",
    "etikett_fuer",
    "frage_aus",
    "quelle_aus",
    "render_abschlusskarte",
]
