"""Ist das ein Foto - oder eine Zeichnung auf weissem Grund?

Die Bildsuche fand fuer "deep sea creature" eine Datei namens
"Humpback anglerfish.png". Lizenz frei, Groesse gut, Form gut, Platz
eins. Und trotzdem falsch: Es ist eine wissenschaftliche Illustration,
freigestellt auf Weiss.

Fuer einen Account ueber tatsaechlich Geschehenes ist das schlimmer als
ein gemaltes Bild. Ein gemaltes gibt vor, eine Vorstellung zu sein. Eine
Strichzeichnung auf Weiss sieht im Feed aus wie ein Versehen.

Ansehen kann dieses Programm ein Bild nicht - dafuer braeuchte es ein
Modell, und das kostet bei jedem Beitrag erneut. Zwei Dinge lassen sich
aber ohne jede Anfrage feststellen, und sie treffen genau diesen Fall:

1. Eine Illustration ist fast immer freigestellt. Der Rand ist dann
   weiss oder einfarbig - bei einer Fotografie praktisch nie.
2. Eine Zeichnung hat wenige Farben. Ein Foto hat Hunderte, auch ein
   dunkles: Rauschen, Verlaeufe, Reflexe.

Beides zusammen faengt Strichzeichnungen, Diagramme, Wappen und
freigestellte Objekte ab, ohne ein einziges echtes Foto zu verwerfen -
jedenfalls keines, das man zeigen wollte.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

log = logging.getLogger(__name__)

# Worauf heruntergerechnet wird, bevor gezaehlt wird. 64x64 reicht fuer
# beide Fragen und kostet nichts.
RASTER = 64

# Ab wann ein Rand als freigestellt gilt.
RANDANTEIL = 0.75
# Und ab welcher Helligkeit ein Punkt als "weiss" zaehlt.
WEISSGRENZE = 232

# Wie viel des ganzen Bildes weiss sein darf, bevor es als Grafik gilt.
WEISSANTEIL = 0.45

# Wie viel Struktur ein Foto mindestens hat. Gemessen wird, wie stark
# sich benachbarte Bildpunkte unterscheiden - im Mittel, ueber das ganze
# Bild.
#
# Das ist der Unterschied, um den es wirklich geht. Eine Zeichnung
# besteht aus Flaechen: Innerhalb einer Flaeche ist der Nachbar derselbe
# Punkt, nur an den Konturen springt es. Eine Fotografie hat ueberall
# Struktur - Korn, Verlauf, Reflex -, auch eine unscharfe und auch eine
# fast schwarze.
#
# Vorher habe ich Farbtoene gezaehlt. Das hat zwei Testfaelle
# umgeworfen, die beide haetten durchgehen muessen: eine Tiefseeaufnahme
# und eine Schneelandschaft. Beide haben wenige Farben und sind
# trotzdem Fotografien - genau die Sorte, um die es diesem Account geht.
# Sehr niedrig angesetzt, und das ist die dritte Fassung dieser Zahl.
#
# Bei 1,2 fielen ein fast schwarzer Nachthimmel und eine neblige
# Aufnahme durch. Bei 0,5 immer noch die neblige: Eine stark
# weichgezeichnete Fotografie kommt auf 0,2 bis 0,3, eine reine
# Farbflaeche auf 0,0.
#
# Also trifft diese Schwelle nur noch den zweiten Fall - eine Flaeche
# ohne jede Zeichnung. Das ist wenig, aber es ist ehrlich: Die
# Weissprobe oben faengt den Fall, um den es wirklich geht, und alles
# darueber hinaus wuerde Fotografien verwerfen, um Grafiken zu treffen.
# Ein verworfenes Foto kostet mehr, denn dann wird gemalt.
MINDESTSTRUKTUR = 0.1

def _randpunkte(punkte: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Die vier Kanten des Rasters, ohne die Mitte."""
    oben = punkte[:RASTER]
    unten = punkte[RASTER * (RASTER - 1) :]
    links = [punkte[RASTER * zeile] for zeile in range(RASTER)]
    rechts = [punkte[RASTER * zeile + RASTER - 1] for zeile in range(RASTER)]
    return oben + unten + links + rechts


def wirkt_wie_foto(pfad: Path) -> tuple[bool, str]:
    """Ob diese Datei wie eine Fotografie aussieht. Mit Begruendung.

    True heisst nicht "schoen", sondern nur: keine Zeichnung, kein
    Diagramm, nichts Freigestelltes. Im Zweifel True - ein Foto
    faelschlich zu verwerfen waere teurer als eine Zeichnung
    durchzulassen, denn dann wird gemalt.
    """
    try:
        with Image.open(pfad) as offen:
            klein = offen.convert("RGB").resize((RASTER, RASTER), Image.BILINEAR)
    except Exception as exc:  # noqa: BLE001 - im Zweifel durchlassen
        log.info("Fotoprobe nicht moeglich (%s): %s", pfad.name, exc)
        return True, ""

    # getdata() ist abgekuendigt; get_flattened_data gibt es erst in
    # neueren Pillow-Fassungen. Beides versuchen, damit es hier und auf
    # dem Rechner des Betreibers laeuft.
    hole = getattr(klein, "get_flattened_data", None) or klein.getdata
    punkte = list(hole())
    ist_weiss = [min(punkt) >= WEISSGRENZE for punkt in punkte]

    rand = _randpunkte(punkte)
    hell_am_rand = sum(1 for punkt in rand if min(punkt) >= WEISSGRENZE)
    if hell_am_rand / len(rand) >= RANDANTEIL:
        return False, "auf Weiss freigestellt - eine Zeichnung, kein Foto"

    weissanteil = sum(ist_weiss) / len(punkte)
    if weissanteil >= WEISSANTEIL:
        return False, f"{round(weissanteil * 100)} Prozent weiss - eine Grafik"

    struktur = _struktur(pfad)
    if struktur is not None and struktur < MINDESTSTRUKTUR:
        return False, f"kaum Struktur ({struktur:.1f}) - eine Grafik, kein Foto"

    return True, ""


def _struktur(pfad: Path) -> float | None:
    """Wie stark sich benachbarte Bildpunkte im Mittel unterscheiden.

    Gemessen am Original, nicht am verkleinerten Raster: Beim
    Herunterrechnen mittelt sich genau das weg, was wir wissen wollen.
    None heisst: nicht feststellbar, dann wird nicht verworfen.
    """
    try:
        with Image.open(pfad) as offen:
            grau = offen.convert("L")
            # Sehr grosse Bilder kosten sonst unnoetig Zeit. 800 Punkte
            # Kantenlaenge reichen, um Korn von Flaeche zu unterscheiden.
            if max(grau.size) > 800:
                faktor = 800 / max(grau.size)
                grau = grau.resize(
                    (max(1, int(grau.width * faktor)), max(1, int(grau.height * faktor))),
                    Image.BILINEAR,
                )
            verschoben = ImageChops.offset(grau, 1, 0)
            unterschied = ImageChops.difference(grau, verschoben)
            # Die erste Spalte ist durch das Umlaufen unbrauchbar.
            unterschied = unterschied.crop((1, 0, unterschied.width, unterschied.height))
            return float(ImageStat.Stat(unterschied).mean[0])
    except Exception as exc:  # noqa: BLE001 - im Zweifel durchlassen
        log.info("Struktur nicht messbar (%s): %s", pfad.name, exc)
        return None


__all__ = ["wirkt_wie_foto"]
