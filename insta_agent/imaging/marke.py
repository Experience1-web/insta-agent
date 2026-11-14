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

from PIL import Image, ImageDraw

from ..models import VisualSpec
from .renderer import FEED, _ensure_readable, _hex_to_rgb, _load_font, _wrap_to_width

# Aus den Themensäulen ein Etikett, das jeder sofort versteht. "Erfunden"
# klingt auf einem Faktenaccount nach "ausgedacht" - deshalb übersetzt.
ETIKETTEN = {
    "ausgegraben": "ARCHÄOLOGIE",
    "erfunden": "FORSCHUNG",
    "lebendig": "NATUR",
    "weltall": "WELTALL",
    "kurios": "KURIOS",
}

RAND = 84
KLEIN = 28


@dataclass(frozen=True)
class Marke:
    """Was zusätzlich zum Hook auf ein Bild gehört."""

    etikett: str = ""
    # "2/6" - leer auf dem ersten Bild, dort steht der Wisch-Hinweis.
    seite: str = ""
    wischen: bool = False


def etikett_fuer(saeule: str) -> str:
    """Das Etikett zu einer Themensäule - kurz, in Großbuchstaben."""
    kopf = (saeule or "").split(":")[0].strip()
    if not kopf:
        return ""
    return ETIKETTEN.get(kopf.casefold(), kopf.upper()[:18])


def _gesperrt(zeichnung, xy, text, schrift, farbe, abstand: int = 3) -> int:
    """Zeichnet Text mit etwas Buchstabenabstand und gibt die Breite zurück."""
    x, y = xy
    for zeichen in text:
        zeichnung.text((x, y), zeichen, font=schrift, fill=farbe)
        x += zeichnung.textlength(zeichen, font=schrift) + abstand
    return int(x - xy[0])


def zeichne_marke(
    bild: Image.Image,
    marke: Marke | None,
    *,
    textfarbe: tuple[int, int, int],
    akzent: tuple[int, int, int],
    familie: str = "klar",
    oben: int = RAND - 18,
) -> None:
    """Etikett oben links, Seitenzähler oben rechts, Wisch-Hinweis unten rechts."""
    if marke is None:
        return
    breite, hoehe = bild.size
    zeichnung = ImageDraw.Draw(bild)
    fett = _load_font(KLEIN, bold=True, familie="klar")
    normal = _load_font(KLEIN, bold=False, familie="klar")

    if marke.etikett:
        # Ein kleiner Punkt in der Akzentfarbe vor dem Wort - das ist das
        # Zeichen, das auf jedem Bild gleich ist.
        zeichnung.ellipse([(RAND, oben + 9), (RAND + 14, oben + 23)], fill=akzent)
        _gesperrt(zeichnung, (RAND + 26, oben), marke.etikett, fett, akzent)

    if marke.seite:
        laenge = zeichnung.textlength(marke.seite, font=normal)
        zeichnung.text((breite - RAND - laenge, oben), marke.seite, font=normal, fill=textfarbe)

    if marke.wischen:
        hinweis = "Wischen  →"
        laenge = zeichnung.textlength(hinweis, font=fett)
        zeichnung.text(
            (breite - RAND - laenge, hoehe - RAND), hinweis, font=fett, fill=textfarbe, anchor="ls"
        )


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
    """Die letzte Karte: die Frage groß, darunter die Quelle, unten Folgen.

    Immer gleich aufgebaut - wer ein paar Beiträge gesehen hat, erkennt
    sie, bevor er sie liest. Sie ist der Grund zu kommentieren, der Beleg
    und die Bitte zu folgen, an der Stelle, an der jemand bis zum Ende
    gewischt hat und damit am meisten Interesse zeigt.
    """
    breite, hoehe = groesse
    grund = _hex_to_rgb(spec.background_hex, (17, 19, 24))
    textfarbe = _ensure_readable(_hex_to_rgb(spec.text_hex, (245, 245, 240)), grund)
    akzent = _hex_to_rgb(spec.accent_hex, (228, 87, 46))
    familie = getattr(spec, "schrift", "klar")

    bild = Image.new("RGB", groesse, grund)
    zeichnung = ImageDraw.Draw(bild)
    zeichnung.rectangle([(0, 0), (breite, 18)], fill=akzent)
    innen = breite - 2 * RAND

    y = int(hoehe * 0.2)
    if frage:
        klein = _load_font(KLEIN, bold=True, familie="klar")
        _gesperrt(zeichnung, (RAND, y), "UND DU?", klein, akzent)
        y += 64
        groesse_frage = 72 if len(frage) < 70 else 60 if len(frage) < 110 else 50
        schrift = _load_font(groesse_frage, bold=True, familie=familie)
        for zeile in _wrap_to_width(zeichnung, frage, schrift, innen)[:6]:
            zeichnung.text((RAND, y), zeile, font=schrift, fill=textfarbe)
            y += int(groesse_frage * 1.22)
        y += 30
        zeichnung.text((RAND, y), "Schreib es in die Kommentare.", font=_load_font(
            34, bold=False, familie=familie), fill=textfarbe)
        y += 90

    if quelle:
        zeichnung.rectangle([(RAND, y), (RAND + 132, y + 8)], fill=akzent)
        y += 36
        klein = _load_font(KLEIN, bold=True, familie="klar")
        _gesperrt(zeichnung, (RAND, y), "QUELLE", klein, akzent)
        y += 46
        schrift = _load_font(32, bold=False, familie=familie)
        for zeile in _wrap_to_width(zeichnung, quelle, schrift, innen)[:4]:
            zeichnung.text((RAND, y), zeile, font=schrift, fill=textfarbe)
            y += 44

    # Unten die Bitte zu folgen - mit dem Grund, nicht nur dem Namen.
    fuss = _load_font(36, bold=True, familie=familie)
    zeichnung.text(
        (RAND, hoehe - RAND - 52), f"Folge {handle}", font=fuss, fill=akzent, anchor="ls"
    )
    zeichnung.text(
        (RAND, hoehe - RAND),
        "Jeden Tag ein Fund, den du sonst verpasst hättest.",
        font=_load_font(28, bold=False, familie=familie),
        fill=textfarbe,
        anchor="ls",
    )

    zeichne_marke(bild, marke, textfarbe=textfarbe, akzent=akzent, familie=familie, oben=60)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ziel, "PNG", optimize=True)
    return ziel


__all__ = [
    "Marke",
    "etikett_fuer",
    "frage_aus",
    "quelle_aus",
    "render_abschlusskarte",
    "zeichne_marke",
]
