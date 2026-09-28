"""Ein Fingerabdruck fuer Bilder - damit "Bild neu" nicht dasselbe bringt.

"Bild neu" suchte wieder ab null und konnte genau das Foto finden, das
man gerade loswerden wollte: Es hatte ja schon einmal gewonnen. Am Namen
laesst sich das nicht erkennen - dasselbe Foto kommt aus dem Archiv, aus
einer Studie oder als verkleinerte Kopie unter anderer Adresse.

Deshalb am Inhalt: Das Bild wird auf 9 x 8 Graustufen verkleinert, und
jedes Bit sagt, ob ein Punkt heller ist als sein rechter Nachbar. Das
bleibt gleich, wenn das Bild groesser, kleiner, etwas heller oder anders
eingefaerbt ist - und unterscheidet sich deutlich, sobald ein anderes
Motiv zu sehen ist.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# Wie viele der 64 Bits abweichen duerfen, damit es noch dasselbe Bild ist.
# Zuschnitt und Farbangleich kosten ein paar; ein anderes Foto liegt
# erfahrungsgemaess weit ueber 20.
GLEICH_BIS = 10


def abdruck(pfad) -> int | None:
    """Der Fingerabdruck eines Bildes, oder None, wenn es sich nicht lesen laesst."""
    try:
        with Image.open(Path(pfad)) as bild:
            grau = bild.convert("L").resize((9, 8), Image.LANCZOS)
            hole = getattr(grau, "get_flattened_data", None) or grau.getdata
            punkte = list(hole())
    except Exception as exc:  # noqa: BLE001 - dann eben kein Abdruck
        log.debug("Kein Abdruck fuer %s: %s", pfad, exc)
        return None
    wert = 0
    for zeile in range(8):
        for spalte in range(8):
            links = punkte[zeile * 9 + spalte]
            rechts = punkte[zeile * 9 + spalte + 1]
            wert = (wert << 1) | (1 if links > rechts else 0)
    return wert


def abstand(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def schon_verwendet(pfad, bekannte) -> bool:
    """Zeigt dieses Bild dasselbe wie eines der schon verwendeten?"""
    if not bekannte:
        return False
    eigen = abdruck(pfad)
    if eigen is None:
        return False
    return any(abstand(eigen, b) <= GLEICH_BIS for b in bekannte if b is not None)


__all__ = ["GLEICH_BIS", "abdruck", "abstand", "schon_verwendet"]
