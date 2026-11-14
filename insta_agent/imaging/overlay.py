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


def _aufhellen_bis_lesbar(
    farbe: tuple[int, int, int], grund: tuple[int, int, int] = (22, 22, 24)
) -> tuple[int, int, int]:
    """Hebt eine Akzentfarbe an, bis sie auf dem dunklen Verlauf trägt.

    Die Bildsprache wählt ihre Akzente für die Schriftfassung; ein
    dunkles Petrol, das dort auf Schwarz noch geht, versinkt auf einem
    Foto. Der Farbton bleibt, nur die Helligkeit steigt.
    """
    r, g, b = farbe
    for _ in range(12):
        if _contrast_ratio((r, g, b), grund) >= 5.5:
            break
        r, g, b = (min(255, int(c + (255 - c) * 0.18)) for c in (r, g, b))
    return (r, g, b)


def _lege_verlauf_oben(bild: Image.Image, bis: int, staerke: int = 160) -> None:
    """Ein Verlauf von oben: am Rand am dunkelsten, nach unten offen.

    Bis ungefähr zur Hälfte der Strecke bleibt er fast voll, damit der
    ganze Textblock auf ruhigem Grund steht, und läuft dann weich aus.
    """
    breite, hoehe = bild.size
    bis = max(1, min(bis, hoehe))
    maske = Image.new("L", (1, bis))
    for y in range(bis):
        anteil = y / bis
        wert = 1.0 if anteil < 0.55 else max(0.0, 1.0 - (anteil - 0.55) / 0.45)
        # Weiches Auslaufen statt einer Geraden - sonst sieht man die Kante.
        maske.putpixel((0, y), int(staerke * (wert ** 1.6)))
    maske = maske.resize((breite, bis))
    bild.paste(Image.new("RGB", (breite, bis), (0, 0, 0)), (0, 0), maske)


def _lege_verlauf_unten(bild: Image.Image, hoehe_verlauf: int, staerke: int = 120) -> None:
    """Ein leichter Verlauf am unteren Rand, damit der Name lesbar bleibt."""
    breite, hoehe = bild.size
    h = max(1, min(hoehe_verlauf, hoehe))
    maske = Image.new("L", (1, h))
    for y in range(h):
        maske.putpixel((0, y), int(staerke * ((y / h) ** 1.4)))
    maske = maske.resize((breite, h))
    bild.paste(Image.new("RGB", (breite, h), (0, 0, 0)), (0, hoehe - h), maske)


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
    marke=None,
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
    akzent = _aufhellen_bis_lesbar(_hex_to_rgb(spec.accent_hex, (228, 87, 46)))

    familie = getattr(spec, "schrift", "klar")
    schrift, zeilen = _fit_text(
        zeichnung, text, innen, int(hoehe * 0.34), start_size=104, min_size=48,
        familie=familie,
    )
    zeilenhoehe = int(getattr(schrift, "size", 80) * 1.16)
    blockhoehe = len(zeilen) * zeilenhoehe

    # Der Hook sitzt im oberen Drittel: Dort schneidet Instagram nichts ab,
    # und der Prompt hat genau dort Platz gelassen.
    oben = int(hoehe * 0.14)

    # Immer ein Verlauf vom oberen Rand bis unter den Text - so machen es
    # die großen Wissens-Accounts. Ein Foto ist nie gleichmäßig, und ein
    # Verlauf sieht nach Absicht aus, nicht nach Notbehelf. Wie stark,
    # hängt vom Grund ab: Auf hellem Grund braucht es mehr.
    grund = _mittlere_helligkeit(bild, (0, oben, breite, oben + blockhoehe))
    unruhig = _contrast_ratio(textfarbe, grund) < MINDESTKONTRAST
    _lege_verlauf_oben(bild, oben + blockhoehe + 140, staerke=215 if unruhig else 150)
    # Unten ein leichter Verlauf für den Namen des Accounts.
    _lege_verlauf_unten(bild, int(hoehe * 0.16), staerke=120)
    zeichnung = ImageDraw.Draw(bild)

    kerne = _akzentkerne(spec, text)
    groesse_px = getattr(schrift, "size", 80)

    # Ein weicher Schatten statt einer harten schwarzen Kontur: Die Kontur
    # trägt zwar überall, sieht aber nach Meme aus. Der Schatten trägt
    # genauso - auch auf einem hellen Fleck mitten im Wort -, und die
    # Buchstaben bleiben sauber.
    schatten = Image.new("L", bild.size, 0)
    schattenzeichnung = ImageDraw.Draw(schatten)
    y = oben
    for zeile in zeilen:
        schattenzeichnung.text(
            (RAND + 2, y + 4),
            zeile,
            font=schrift,
            fill=255,
            stroke_width=max(2, round(groesse_px * KONTUR * 0.7)),
            stroke_fill=255,
        )
        y += zeilenhoehe
    schatten = schatten.filter(ImageFilter.GaussianBlur(max(4, groesse_px // 9)))
    schatten = schatten.point(lambda v: min(255, int(v * 0.85)))
    bild.paste(Image.new("RGB", bild.size, (0, 0, 0)), (0, 0), schatten)
    zeichnung = ImageDraw.Draw(bild)

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
            kontur=0,
        )
        y += zeilenhoehe

    # Die Akzentlinie ist das Wiedererkennungszeichen im Feed.
    zeichnung.rectangle([(RAND, y + 22), (RAND + 132, y + 32)], fill=akzent)

    fuss = (handle or spec.footer).strip()
    if fuss:
        fussschrift = _load_font(32, bold=False, familie=familie)
        zeichnung.text(
            (RAND, hoehe - RAND), fuss, font=fussschrift, fill=textfarbe, anchor="ls"
        )

    if marke is not None:
        from .marke import zeichne_marke

        zeichne_marke(bild, marke, textfarbe=textfarbe, akzent=akzent, familie=familie)

    ziel.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ziel, "PNG", optimize=True)
    return ziel


__all__ = ["lege_hook_auf", "_auf_format", "_akzentkerne", "_wrap_to_width"]
