"""Prüfen, ob eine gefundene Aufnahme wirklich scharf ist.

Die Auflösung sagt das nicht. Ein Bild kann 2400 Pixel breit sein und
trotzdem weich aussehen - ein Standbild aus einem Video, ein Scan, eine
Aufnahme, die schon einmal hochgerechnet wurde. Genau so eines ist im
Beitrag gelandet, und man sah es sofort.

Gemessen wird deshalb nicht die Pixelzahl, sondern, ob zwischen
benachbarten Bildpunkten überhaupt noch etwas passiert - und zwar an
dem Bild, das am Ende erscheint, nicht am Original. Das ist der
entscheidende Unterschied: Eine weiche 3000er-Aufnahme, auf 1080
heruntergerechnet, sieht gut aus. Dasselbe Bild auf 1080 hochgerechnet
nicht. Die Frage ist immer, was ankommt.

Die Kennzahl ist ein Verhältnis, und das ist Absicht. Verglichen wird,
wie stark sich ein Bild von seinem um einen Bildpunkt verschobenen
Selbst unterscheidet, mit demselben bei zwei Bildpunkten Versatz. Bei
einer scharfen Aufnahme steckt die Kante schon im einen Bildpunkt, das
Verhältnis liegt nahe eins. Bei einer weichen ist ein Bildpunkt noch
nichts und zwei erst etwas - das Verhältnis fällt.

Der Vorteil dieser Form: Der Motivkontrast kürzt sich heraus. Eine
Nebelaufnahme und ein Feuerwerk werden gleich behandelt, obwohl das
eine kaum und das andere sehr viel Kantenenergie hat. Eine absolute
Schwelle hätte den Nebel verworfen - so ist das schon einmal
schiefgegangen, bei der Frage, ob etwas ein Foto ist.

Gemessen wird in Kacheln, und genommen wird die beste. Ein Foto mit
offener Blende ist im Hintergrund unscharf und soll es sein; scharf
sein muss das Motiv. Über das ganze Bild gemittelt fiele so eine
Aufnahme durch, obwohl sie die bessere ist.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

log = logging.getLogger(__name__)

# Das Format, in dem der Beitrag erscheint. Daran wird gemessen.
ZIELGROESSE = (1080, 1350)

# Wie fein gekachelt wird. Drei mal drei ist der Punkt, an dem eine
# Kachel gross genug fuer eine belastbare Messung und klein genug ist,
# um ein scharfes Motiv vom weichen Hintergrund zu trennen.
KACHELN = 3

# Ab hier gilt eine Aufnahme als scharf genug. Ausgemessen an
# Vergleichsbildern:
#
#   scharf, unveraendert            0,88
#   von 1256 auf 1080 verkleinert   0,78
#   um das 1,23-fache hochgerechnet 0,70
#   leicht weichgezeichnet          0,58
#   auf das Doppelte hochgerechnet  0,56
#   deutlich weichgezeichnet        0,51
#
# 0,62 liegt in der Luecke dazwischen, naeher an den unscharfen: Lieber
# ein weiches Bild zu viel durchlassen als ein gutes verwerfen - es
# gibt nicht so viele frei verwendbare Aufnahmen, dass man waehlerisch
# sein koennte.
SCHARF_GENUG = 0.62

# Unter so viel Unterschied ist eine Kachel eine leere Flaeche - Himmel,
# Wand, Tiefsee. Dort ist nichts zu messen, und das Verhaeltnis waere
# nur noch Rauschen geteilt durch Rauschen.
MINDESTUNTERSCHIED = 0.5


def _auf_zielgroesse(bild: Image.Image, groesse: tuple[int, int]) -> Image.Image:
    """Dasselbe Beschneiden wie beim Beitrag - aber ohne Nachschaerfen.

    Nachgeschaerft wird beim Beitrag bewusst; hier waere es Betrug an
    der eigenen Messung, denn dann bestuende das Bild die Pruefung
    wegen der Nachbearbeitung und nicht wegen seiner Qualitaet.
    """
    if bild.size == groesse:
        return bild
    ziel_b, ziel_h = groesse
    faktor = max(ziel_b / bild.width, ziel_h / bild.height)
    neu = bild.resize(
        (round(bild.width * faktor), round(bild.height * faktor)), Image.LANCZOS
    )
    links = (neu.width - ziel_b) // 2
    oben = max(0, int((neu.height - ziel_h) * 0.4))
    return neu.crop((links, oben, links + ziel_b, oben + ziel_h))


def _kennzahl(grau: Image.Image) -> float:
    """Das Verhaeltnis von Ein-Pixel- zu Zwei-Pixel-Unterschied."""

    def unterschied(versatz: int) -> float:
        verschoben = ImageChops.offset(grau, versatz, 0)
        return ImageStat.Stat(ImageChops.difference(grau, verschoben)).mean[0]

    zwei = unterschied(2)
    if zwei < MINDESTUNTERSCHIED:
        return 0.0
    return unterschied(1) / zwei


def schaerfewert(
    pfad: Path, *, groesse: tuple[int, int] = ZIELGROESSE, kacheln: int = KACHELN
) -> float:
    """Wie scharf dieses Bild im Beitrag ankommt. 0 heisst: nicht messbar.

    Zurueck kommt die beste Kachel, nicht der Durchschnitt - siehe oben.
    """
    try:
        with Image.open(pfad) as offen:
            grau = _auf_zielgroesse(offen.convert("RGB"), groesse).convert("L")
    except Exception as exc:  # noqa: BLE001 - dann eben keine Aussage
        log.info("Schaerfe nicht gemessen (%s): %s", Path(pfad).name, exc)
        return 0.0

    breite, hoehe = grau.size
    werte = []
    for zeile in range(kacheln):
        for spalte in range(kacheln):
            kachel = grau.crop(
                (
                    spalte * breite // kacheln,
                    zeile * hoehe // kacheln,
                    (spalte + 1) * breite // kacheln,
                    (zeile + 1) * hoehe // kacheln,
                )
            )
            if wert := _kennzahl(kachel):
                werte.append(wert)
    return max(werte) if werte else 0.0


def ist_scharf(
    pfad: Path,
    *,
    groesse: tuple[int, int] = ZIELGROESSE,
    mindestens: float = SCHARF_GENUG,
) -> tuple[bool, str]:
    """Ob diese Aufnahme scharf genug ist. Dazu der Grund im Klartext.

    Ein Bild, an dem sich nichts messen laesst, gilt als scharf: Eine
    Messung, die nichts gefunden hat, ist kein Grund zu verwerfen.
    """
    wert = schaerfewert(pfad, groesse=groesse)
    if wert <= 0:
        return True, "Schaerfe nicht messbar"
    if wert < mindestens:
        return False, f"unscharf im Beitragsformat ({wert:.2f})"
    return True, f"scharf ({wert:.2f})"


__all__ = ["SCHARF_GENUG", "ist_scharf", "schaerfewert"]
