"""Den Hook auf ein erzeugtes Bild legen - und zwar lesbar.

Ein Foto ist nie gleichmäßig hell. Weißer Text auf einem hellen Fleck ist
unsichtbar, und genau der Satz, wegen dem der Daumen stehenbleiben soll,
wäre dann weg. Deshalb dreierlei: Es wird gemessen, wo es ruhig und dunkel
genug ist, notfalls ein Verlauf daruntergelegt, und die Schrift bekommt
eine dünne dunkle Kontur. Die Kontur trägt auch da, wo ein heller Fleck
mitten im Wort sitzt - dafür reicht kein Verlauf.

Ein Wort steht in der Akzentfarbe: die Zahl, die Tiefe, der Name - das,
woran die Sache hängt. Das ist der Unterschied zwischen einer Bildunter-
schrift und einer Schlagzeile. Wer alles hervorhebt, hebt nichts hervor,
deshalb höchstens zwei Wörter.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ..models import VisualSpec
from .renderer import (
    KONTUR,
    STORY,
    _akzentkerne,
    _contrast_ratio,
    _fit_text,
    _hex_to_rgb,
    _load_font,
    _wrap_to_width,
    _zeichne_zeile,
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


def _nachschaerfen(bild: Image.Image, faktor: float) -> Image.Image:
    """Die Schaerfe zurueckholen, die das Skalieren gekostet hat.

    Jede Umrechnung mittelt benachbarte Bildpunkte, und Mitteln ist
    genau das, was Unschaerfe ist. Beim Verkleinern faellt das kaum auf,
    beim Vergroessern sehr. Ein Nachschaerfen hebt die Kanten wieder an -
    derselbe Handgriff, den jedes Bildbearbeitungsprogramm nach dem
    Aendern der Groesse vorschlaegt.

    Die Schwelle ist wichtig: Ohne sie wuerde auch das Rauschen in
    dunklen Flaechen mit angehoben, und dann sieht ein Nachthimmel
    griesselig aus.
    """
    if abs(faktor - 1.0) < 0.02:
        return bild
    if faktor < 1.0:
        # Verkleinert - da reicht wenig, sonst sieht man Raender an Kanten.
        return bild.filter(ImageFilter.UnsharpMask(radius=1.0, percent=65, threshold=3))
    # Vergroessert - hier ist wirklich Schaerfe verlorengegangen.
    return bild.filter(ImageFilter.UnsharpMask(radius=1.6, percent=90, threshold=2))


def _auf_format(bild: Image.Image, groesse: tuple[int, int] = STORY) -> Image.Image:
    """Bringt ein Bild auf das Beitragsformat - durch Beschneiden, nie durch Zerren.

    `groesse` ist FEED (1080x1350) oder STORY (1080x1920), und dass das
    ueberhaupt ein Parameter ist, war der Fehler: Vorher landete jedes
    Bild auf 9:16, auch wenn der Beitrag als Feed-Beitrag eingestellt war.

    Das kostete zweierlei auf einmal. Instagram zeigt im Feed hoechstens
    4:5, also wurde von einem 9:16-Bild oben und unten etwas abgeschnitten -
    unter anderem vom Hook. Und schlimmer: Eine Querformataufnahme von
    2400 x 1565 muss fuer 1920 Pixel Hoehe um das 1,23-fache hochgerechnet
    werden, fuer 1350 dagegen auf das 0,86-fache herunter. Ein
    hochgerechnetes Bild ist unscharf, und man sieht es sofort.

    Die Anbieter liefern unterschiedliche Seitenverhaeltnisse. Einfach auf
    die Zielgroesse zu strecken wuerde Gesichter und Geraden verziehen,
    deshalb wird auf Ueberdeckung skaliert und mittig beschnitten.
    """
    if bild.size == groesse:
        return bild

    ziel_b, ziel_h = groesse
    faktor = max(ziel_b / bild.width, ziel_h / bild.height)
    neu_b, neu_h = round(bild.width * faktor), round(bild.height * faktor)
    bild = bild.resize((neu_b, neu_h), Image.LANCZOS)
    bild = _nachschaerfen(bild, faktor)

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
    groesse: tuple[int, int] = STORY,
) -> Path:
    """Schreibt den Hook auf das erzeugte Bild und speichert das Ergebnis.

    `groesse` muss dasselbe Format sein, in dem der Beitrag erscheint -
    sonst wird das Bild auf ein Format gebracht, das Instagram danach
    noch einmal beschneidet.
    """
    bild = _auf_format(Image.open(quelle).convert("RGB"), groesse)

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

    kerne = _akzentkerne(spec, text)
    kontur = max(2, round(getattr(schrift, "size", 80) * KONTUR))

    y = oben
    for zeile in zeilen:
        _zeichne_zeile(
            zeichnung,
            (RAND, y),
            zeile,
            schrift=schrift,
            textfarbe=textfarbe,
            akzent=akzent,
            kerne=kerne,
            kontur=kontur,
        )
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


__all__ = ["lege_hook_auf", "_auf_format", "_akzentkerne", "_wrap_to_width"]
