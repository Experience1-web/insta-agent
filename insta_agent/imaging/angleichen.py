"""Mehrere Bilder eines Beitrags zueinander passend machen.

Ein Karussell aus fünf Bildern, die aus fünf Welten stammen, ist ein
Sammelsurium. Wer wischt, soll merken, dass er noch im selben Beitrag
ist - und das merkt er an der Farbe, bevor er den Text liest.

Bei gemalten Bildern lässt sich das über den Prompt regeln: dieselbe
Lichtstimmung, dieselbe Farbwelt. Bei echten Aufnahmen nicht. Die eine
ist ein kühles Teleskopbild, die nächste eine warme Grabungsaufnahme aus
den Achtzigern, und nebeneinander sieht das aus wie zwei Beiträge.

Also wird nachgearbeitet - mit Pillow, das ohnehin schon dabei ist, und
ohne jeden fremden Dienst. Drei Handgriffe, wie sie ein Mensch in einem
Bildbearbeitungsprogramm auch machen würde:

1. Eine leichte Farbstimmung in Richtung der Beitragsfarben legen.
2. Kontrast und Sättigung auf einen gemeinsamen Nenner bringen.
3. Alles nur zu einem Teil, nicht ganz.

Der dritte Punkt ist der wichtige. Ein durchgefärbtes Foto sieht aus wie
ein Filter, und ein Filter sieht billig aus. Es geht darum, dass die
Bilder zueinander passen, nicht darum, dass man die Bearbeitung sieht.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from .renderer import _hex_to_rgb

log = logging.getLogger(__name__)

# Wie stark die gemeinsame Farbstimmung durchschlägt. Ausprobiert an
# zwei Aufnahmen, die weiter auseinanderliegen als alles, was in einem
# Beitrag je zusammenkommt - eine kalt-blaue und eine warm-braune:
#
#   0,22  Farbabstand 167 -> 136   kaum zu sehen
#   0,30  Farbabstand 167 -> 126   sie gehoeren erkennbar zusammen
#   0,50  Farbabstand 167 ->  99   sieht nach Filter aus
#
# 0,30 ist der Punkt, an dem man die Verwandtschaft sieht und die
# Bearbeitung nicht.
STAERKE = 0.30

# Worauf Kontrast und Sättigung gezogen werden. Leicht über eins, weil
# Archivaufnahmen meist flauer sind als gemalte Bilder.
KONTRAST = 1.08
SAETTIGUNG = 0.86

# Wie weit ein Bild der Helligkeit des ersten entgegenwandert. Ganz
# waere falsch: Fuenf gleich helle Bilder sind genauso tot wie fuenf
# verschiedene.
ANGLEICH = 0.66


def _farbstimmung(
    bild: Image.Image,
    dunkel: tuple[int, int, int],
    hell: tuple[int, int, int],
    staerke: float,
) -> Image.Image:
    """Legt eine Zweifarben-Stimmung über das Bild.

    Die Tiefen wandern zur dunklen Farbe, die Lichter zur hellen - so
    arbeitet jede Farbkorrektur im Film. Gerechnet wird über die
    Helligkeit, damit die Zeichnung im Bild erhalten bleibt.
    """
    # ImageOps.colorize bildet den Graukeil auf zwei Farben ab - genau
    # das, was eine Zweifarben-Stimmung ist, und in C statt in Python.
    getoent = ImageOps.colorize(bild.convert("L"), black=dunkel, white=hell)
    return Image.blend(bild.convert("RGB"), getoent, staerke)


def _helligkeit(bild: Image.Image) -> float:
    """Die mittlere Helligkeit, 0 bis 255."""
    ein_pixel = bild.convert("L").resize((1, 1), Image.LANCZOS)
    return float(ein_pixel.getpixel((0, 0)))


def gleiche_reihe_an(
    pfade: list[Path],
    *,
    hintergrund_hex: str,
    akzent_hex: str,
    staerke: float = STAERKE,
) -> int:
    """Zieht eine ganze Bilderreihe zusammen. Gibt zurueck, wie viele klappten.

    Der Unterschied zu `gleiche_an` ist nicht die Bequemlichkeit, sondern
    die Helligkeit - und die ist es, an der eine Reihe auseinanderfaellt.
    Eine Farbstimmung laesst sich an einem einzelnen Bild anlegen; dass
    ein Bild heller ist als das daneben, sieht man erst im Vergleich.
    Gemessen an fuenf sehr verschiedenen Aufnahmen bringt die Farbstimmung
    allein den Abstand von 182 auf 166 - die Helligkeit dazu auf 96.

    Das erste Bild gibt den Ton an und bleibt unangetastet: Es ist das,
    was im Feed erscheint, und die Schriftfarben wurden dafuer gewaehlt.
    Die anderen wandern ihm entgegen, aber nur zu zwei Dritteln - ganz
    angeglichen waeren es fuenf gleich helle Flaechen.
    """
    if not pfade:
        return 0

    try:
        with Image.open(pfade[0]) as erstes:
            ziel = _helligkeit(erstes.convert("RGB"))
    except Exception as exc:  # noqa: BLE001 - dann eben ohne gemeinsames Ziel
        log.warning("Reihe nicht gemessen: %s", exc)
        ziel = 0.0

    geschafft = 0
    for nummer, pfad in enumerate(pfade):
        # Das erste bekommt nur die Farbstimmung, keine Helligkeitskorrektur.
        angleich = None if nummer == 0 or ziel <= 0 else ziel
        if gleiche_an(
            pfad,
            hintergrund_hex=hintergrund_hex,
            akzent_hex=akzent_hex,
            staerke=staerke,
            zielhelligkeit=angleich,
        ):
            geschafft += 1
    return geschafft


def gleiche_an(
    pfad: Path,
    *,
    hintergrund_hex: str,
    akzent_hex: str,
    staerke: float = STAERKE,
    zielhelligkeit: float | None = None,
) -> bool:
    """Zieht ein Bild in die Farbwelt des Beitrags. True, wenn es klappte.

    `zielhelligkeit` ist die mittlere Helligkeit, auf die zugegangen wird -
    gesetzt von `gleiche_reihe_an`, wenn mehrere Bilder zusammengehoeren.
    Allein steht sie auf None: Ein einzelnes Bild hat nichts, wozu es
    passen muesste.

    `hintergrund_hex` und `akzent_hex` sind die Farben, die die
    Bildsprache für diesen Beitrag festgelegt hat - dieselben, in denen
    die Schrift gesetzt wird. Damit gehört das Bild sichtbar dazu.

    Schlägt es fehl, bleibt das Bild, wie es war: Ein unbearbeitetes Foto
    ist immer noch besser als kein Foto.
    """
    try:
        dunkel = _hex_to_rgb(hintergrund_hex, (17, 19, 24))
        # Nicht die Akzentfarbe selbst in die Lichter legen - die ist oft
        # kräftig, und kräftige Lichter sehen nach Kitsch aus. Stattdessen
        # ein sehr helles Grau mit einem Hauch davon.
        akzent = _hex_to_rgb(akzent_hex, (228, 87, 46))
        hell = tuple(min(255, int(235 + (wert - 128) * 0.12)) for wert in akzent)

        with Image.open(pfad) as offen:
            bild = offen.convert("RGB")

        if zielhelligkeit and zielhelligkeit > 0:
            ist = _helligkeit(bild)
            if ist > 4:
                # Zu zwei Dritteln, nicht ganz: Fuenf gleich helle Bilder
                # waeren ebenso falsch wie fuenf verschiedene.
                faktor = 1.0 + (zielhelligkeit / ist - 1.0) * ANGLEICH
                bild = ImageEnhance.Brightness(bild).enhance(
                    max(0.35, min(2.2, faktor))
                )

        bild = _farbstimmung(bild, dunkel, hell, max(0.0, min(0.6, staerke)))
        bild = ImageEnhance.Contrast(bild).enhance(KONTRAST)
        bild = ImageEnhance.Color(bild).enhance(SAETTIGUNG)
        bild.save(pfad)
        return True
    except Exception as exc:  # noqa: BLE001 - lieber unbearbeitet als gar nicht
        log.warning("Bild nicht angeglichen (%s): %s", pfad.name, exc)
        return False


__all__ = ["gleiche_an", "gleiche_reihe_an"]
