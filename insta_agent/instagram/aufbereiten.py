"""Ein Bild so zurechtlegen, dass Instagram es annimmt.

Zwei Bedingungen, die beide nicht verhandelbar sind:

1. JPEG. Die Veröffentlichungs-Schnittstelle lehnt PNG ab, und zwar mit
   der wenig hilfreichen Meldung "Only photo or video can be accepted as
   media type".
2. Ein Seitenverhältnis zwischen 4:5 (hochkant) und 1.91:1 (quer). Das
   9:16 der Reels liegt außerhalb - im Feed geht es nicht.

Der lokale Entwurf bleibt unangetastet: Er ist verlustfrei und wird im
Dashboard angezeigt. Nur die Fassung, die hinausgeht, wird umgerechnet.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# Instagrams Grenzen für Feed-Beiträge, als Breite geteilt durch Höhe.
SCHMALSTE = 0.80  # 4:5, hochkant
BREITESTE = 1.91  # Panorama

# Was Instagram bei zu grossen Dateien ablehnt, liegt bei 8 MB. 88 ist
# ein guter Kompromiss: sichtbar sauber, weit unter der Grenze.
GUETE = 88


def _auf_erlaubtes_verhaeltnis(bild: Image.Image) -> Image.Image:
    """Beschneidet, bis das Bild in Instagrams Rahmen passt.

    Beschnitten wird vom unteren Rand her: Im Hochformat steht der Hook
    oben, und der ist der Grund, warum jemand stehenbleibt. Ihn
    abzuschneiden wäre das Schlimmste, was man tun kann.
    """
    breite, hoehe = bild.size
    verhaeltnis = breite / hoehe

    if SCHMALSTE <= verhaeltnis <= BREITESTE:
        return bild

    if verhaeltnis < SCHMALSTE:
        # Zu hoch: Höhe kürzen, oben bleibt stehen.
        neue_hoehe = round(breite / SCHMALSTE)
        log.info("Bild von %dx%d auf %dx%d gekürzt", breite, hoehe, breite, neue_hoehe)
        return bild.crop((0, 0, breite, neue_hoehe))

    # Zu breit: mittig beschneiden, da gibt es kein Oben und Unten.
    neue_breite = round(hoehe * BREITESTE)
    links = (breite - neue_breite) // 2
    log.info("Bild von %dx%d auf %dx%d gekürzt", breite, hoehe, neue_breite, hoehe)
    return bild.crop((links, 0, links + neue_breite, hoehe))


def fuer_instagram(pfad: Path) -> bytes:
    """Gibt die Bytes zurück, die Instagram annimmt: JPEG im erlaubten Rahmen."""
    with Image.open(pfad) as roh:
        # JPEG kennt keine Transparenz; ein RGBA-Bild würde sonst scheitern.
        bild = roh.convert("RGB")
        bild = _auf_erlaubtes_verhaeltnis(bild)

        puffer = io.BytesIO()
        bild.save(puffer, "JPEG", quality=GUETE, optimize=True, progressive=True)
        return puffer.getvalue()
