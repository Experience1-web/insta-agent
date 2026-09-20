"""Den Hook auf ein erzeugtes Bild legen - und zwar lesbar.

Ein Foto ist nie gleichmäßig hell. Weißer Text auf einem hellen Fleck ist
unsichtbar, und genau der Satz, wegen dem der Daumen stehenbleiben soll,
wäre dann weg. Deshalb wird gemessen, wo es ruhig und dunkel genug ist,
und notfalls ein Verlauf daruntergelegt.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ..models import VisualSpec
from .renderer import (
    STORY,
    _contrast_ratio,
    _fit_text,
    _hex_to_rgb,
    _load_font,
    _wrap_to_width,
)

log = logging.getLogger(__name__)

RAND = 84
# Unter diesem Verhältnis ist Text auf Bildgrund nicht mehr angenehm zu lesen.
MINDESTKONTRAST = 4.5


def _mittlere_helligkeit(bild: Image.Image, kasten: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Die Durchschnittsfarbe eines Ausschnitts - das ist der Grund des Textes.

    Auf ein Pixel herunterzurechnen mittelt genau das, was wir wissen
    wollen, und braucht keine Schleife über Zehntausende Bildpunkte.
    """
    ein_pixel = bild.crop(kasten).resize((1, 1), Image.LANCZOS)
    r, g, b = ein_pixel.getpixel((0, 0))[:3]
    return (r, g, b)


def _lege_schleier(bild: Image.Image, oben: int, unten: int, staerke: int = 190) -> None:
    """Ein weicher dunkler Verlauf, damit heller Text überall trägt.

    Bewusst ein Verlauf und kein Balken: Ein harter Kasten sieht nach
    Nachbearbeitung aus, ein Verlauf nach Absicht.
    """
    breite = bild.width
    hoehe = max(unten - oben, 1)
    schleier = Image.new("L", (1, hoehe))
    for y in range(hoehe):
        # In der Mitte des Textbereichs am dunkelsten, zu den Rändern hin offen.
        anteil = 1.0 - abs((y / hoehe) * 2 - 1)
        schleier.putpixel((0, y), int(staerke * anteil))
    schleier = schleier.resize((breite, hoehe)).filter(ImageFilter.GaussianBlur(18))

    dunkel = Image.new("RGB", (breite, hoehe), (0, 0, 0))
    bild.paste(dunkel, (0, oben), schleier)


def _auf_hochformat(bild: Image.Image) -> Image.Image:
    """Bringt jedes Bild auf 9:16 - durch Beschneiden, nie durch Zerren.

    Die Anbieter liefern unterschiedliche Seitenverhältnisse; manche
    können 9:16 gar nicht. Einfach auf die Zielgröße zu strecken würde
    Gesichter und Geraden verziehen, und das sieht man sofort. Deshalb
    wird auf Überdeckung skaliert und mittig beschnitten.
    """
    if bild.size == STORY:
        return bild

    ziel_b, ziel_h = STORY
    faktor = max(ziel_b / bild.width, ziel_h / bild.height)
    neu_b, neu_h = round(bild.width * faktor), round(bild.height * faktor)
    bild = bild.resize((neu_b, neu_h), Image.LANCZOS)

    links = (neu_b - ziel_b) // 2
    # Etwas oberhalb der Mitte beschneiden: Im Hochformat liegt das Motiv
    # meist über der Mitte, und oben steht ohnehin der Hook.
    oben = max(0, int((neu_h - ziel_h) * 0.4))
    return bild.crop((links, oben, links + ziel_b, oben + ziel_h))


def lege_hook_auf(
    quelle: Path,
    ziel: Path,
    *,
    text: str,
    spec: VisualSpec,
    handle: str = "",
) -> Path:
    """Schreibt den Hook auf das erzeugte Bild und speichert das Ergebnis."""
    bild = _auf_hochformat(Image.open(quelle).convert("RGB"))

    breite, hoehe = bild.size
    zeichnung = ImageDraw.Draw(bild)
    innen = breite - 2 * RAND

    textfarbe = _hex_to_rgb(spec.text_hex, (247, 245, 239))
    akzent = _hex_to_rgb(spec.accent_hex, (228, 87, 46))

    schrift, zeilen = _fit_text(
        zeichnung, text, innen, int(hoehe * 0.34), start_size=104, min_size=48
    )
    zeilenhoehe = int(getattr(schrift, "size", 80) * 1.16)
    blockhoehe = len(zeilen) * zeilenhoehe

    # Der Hook sitzt im oberen Drittel: Dort schneidet Instagram nichts ab,
    # und der Prompt hat genau dort Platz gelassen.
    oben = int(hoehe * 0.14)

    grund = _mittlere_helligkeit(bild, (0, oben, breite, oben + blockhoehe))
    if _contrast_ratio(textfarbe, grund) < MINDESTKONTRAST:
        _lege_schleier(bild, max(oben - 90, 0), min(oben + blockhoehe + 90, hoehe))
        log.debug("Schleier gelegt, der Bildgrund war zu unruhig")

    y = oben
    for zeile in zeilen:
        zeichnung.text((RAND, y), zeile, font=schrift, fill=textfarbe)
        y += zeilenhoehe

    # Die Akzentlinie ist das Wiedererkennungszeichen im Feed.
    zeichnung.rectangle([(RAND, y + 22), (RAND + 132, y + 32)], fill=akzent)

    fuss = (handle or spec.footer).strip()
    if fuss:
        fussschrift = _load_font(32, bold=False)
        zeichnung.text(
            (RAND, hoehe - RAND), fuss, font=fussschrift, fill=textfarbe, anchor="ls"
        )

    ziel.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ziel, "PNG", optimize=True)
    return ziel


__all__ = ["lege_hook_auf", "_wrap_to_width"]
