"""Ein breites Bild in ein Karussell zerschneiden, durch das man wandert.

Instagram hat dafür keine Funktion. Es ist ein Kniff, und er funktioniert,
weil ein Karussell seine Bilder beim Wischen unmittelbar nebeneinander
zeigt: Schneidet man ein Panorama in gleich breite Stücke und lädt sie in
der richtigen Reihenfolge hoch, läuft das Bild beim Wischen weiter, als
wäre es eines.

Der Effekt ist die halbe Sache wert. Jemand, der wischt, merkt nach dem
zweiten Bild, dass er nicht durch Kacheln blättert, sondern an einer
Aufnahme entlangfährt - und wischt dann bis zum Ende. Genau das zählt bei
Instagram mehr als alles andere.

Dafür gilt eine Regel, die man nicht verhandeln kann: **Text nur auf dem
ersten Stück.** Eine Zeile auf jedem Teilstück zerhackt die Aufnahme und
nimmt ihr genau das, wofür man sie genommen hat. Die Fakten stehen dann
in der Bildunterschrift, nicht im Bild.

Verwendet wird das nur, wenn wirklich ein breites Bild vorliegt. Aus
einem gewöhnlichen Querformat drei Stücke zu schneiden ergibt drei
angeschnittene Bilder und kein Panorama.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image

from .overlay import _nachschaerfen

log = logging.getLogger(__name__)

# Ab diesem Seitenverhältnis lohnt es sich. Darunter ist es ein normales
# Querformat, und das schneidet man nicht auseinander.
MINDESTVERHAELTNIS = 2.2

# Mehr Stücke liest niemand zu Ende, weniger als zwei sind kein Karussell.
MIN_STUECKE = 2
MAX_STUECKE = 5

# Kleiner darf ein Teilstück nicht werden. Die Zahl liegt unter den 1080
# Pixeln, die Instagram zeigt, und das ist Absicht: Ein Stück von 700 auf
# 864 hochzurechnen sind 23 Prozent und sieht man nicht. Strenger zu sein
# hätte ein 8:1-Band abgelehnt, dessen Höhe völlig ausreicht - die
# Stücke sind dort nicht zu klein, sondern nur so hoch wie das Band.
MINDESTBREITE_STUECK = 700


def ist_panorama(pfad: Path, *, mindestens: float = MINDESTVERHAELTNIS) -> bool:
    """Ob dieses Bild breit genug ist, dass ein Durchwandern etwas bringt."""
    try:
        with Image.open(pfad) as bild:
            breite, hoehe = bild.size
    except Exception as exc:  # noqa: BLE001 - dann eben kein Panorama
        log.info("Panorama nicht geprüft (%s): %s", pfad.name, exc)
        return False
    return hoehe > 0 and (breite / hoehe) >= mindestens


def stueckzahl(breite: int, hoehe: int, zielverhaeltnis: float) -> int:
    """Wie viele Teilstücke aus diesem Bild werden.

    Aufgerundet, nicht gerundet - und das ist kein Detail. Jedes Stück
    behält die volle Breite, die ihm zusteht, sonst klafft an der Naht
    eine Lücke. Die Höhe darf dafür beschnitten werden, die Breite nicht.

    Aufgerundet ist jedes Stück schmaler als hoch mal Zielverhältnis, und
    dann bleibt oben und unten etwas zum Wegschneiden. Abgerundet wäre es
    breiter, und dann müsste man in der Breite beschneiden - genau das,
    was die Naht zerstört.
    """
    if hoehe <= 0 or zielverhaeltnis <= 0:
        return 0
    noetig = math.ceil((breite / hoehe) / zielverhaeltnis)
    zahl = max(MIN_STUECKE, min(MAX_STUECKE, noetig))

    # Wie breit ein Stück tatsächlich wird. Reicht die Länge nicht für so
    # viele Stücke, gibt der Deckel nach; reicht sie für mehr, wird nur
    # die Mitte genommen (das entscheidet `zerschneide`).
    nutzbreite = min(breite, int(zahl * hoehe * zielverhaeltnis))

    # Lieber ein Stück weniger als Stücke, die hochgerechnet werden müssen.
    while zahl > MIN_STUECKE and nutzbreite // zahl < MINDESTBREITE_STUECK:
        zahl -= 1
        nutzbreite = min(breite, int(zahl * hoehe * zielverhaeltnis))
    if nutzbreite // zahl < MINDESTBREITE_STUECK:
        return 0
    return zahl


def zerschneide(
    quelle: Path,
    ziel_stamm: Path,
    *,
    format_breite: int,
    format_hoehe: int,
) -> list[Path]:
    """Schneidet ein Panorama in Teilstücke. Leer heisst: lohnt sich nicht.

    Die Stücke schließen ohne Lücke und ohne Überlappung aneinander an -
    beides sieht man beim Wischen sofort. Die volle Höhe wird genutzt und
    nur in der Breite geteilt; oben und unten etwas wegzunehmen würde die
    Naht nicht verbessern, aber Bild kosten.
    """
    try:
        with Image.open(quelle) as offen:
            bild = offen.convert("RGB")
            breite, hoehe = bild.size

            zahl = stueckzahl(breite, hoehe, format_breite / format_hoehe)
            if zahl < MIN_STUECKE:
                return []

            verhaeltnis = format_breite / format_hoehe

            # Ein sehr langes Panorama braucht mehr Stücke, als jemand
            # durchwischt. Bei fünf ist Schluss - dann wird nicht
            # gequetscht, sondern der mittlere Ausschnitt genommen. Ein
            # 5:1-Band ergibt so fünf saubere Stücke aus seiner Mitte
            # statt fünf gestauchte aus der ganzen Länge.
            nutzbreite = min(breite, int(zahl * hoehe * verhaeltnis))
            links_rand = (breite - nutzbreite) // 2

            # Ganzzahlig teilen und den Rest gleichmäßig verteilen, sonst
            # ist das letzte Stück schmaler und die Naht sichtbar.
            stueck = nutzbreite // zahl
            versatz = links_rand + (nutzbreite - stueck * zahl) // 2

            # Wie hoch ein Stück sein darf, damit es unverzerrt ins
            # Zielformat passt. Mehr waere Verzerrung, weniger waere
            # verschenktes Bild.
            nutzhoehe = min(hoehe, round(stueck / verhaeltnis))
            oben = max(0, (hoehe - nutzhoehe) // 2)

            teile: list[Path] = []
            for i in range(zahl):
                links = versatz + i * stueck
                ausschnitt = bild.crop((links, oben, links + stueck, oben + nutzhoehe))
                vorher = ausschnitt.width
                ausschnitt = ausschnitt.resize(
                    (format_breite, format_hoehe), Image.LANCZOS
                )
                # Dasselbe Nachschaerfen wie beim gewoehnlichen Bild -
                # sonst ist ausgerechnet das Karussell, das am laengsten
                # angesehen wird, das weichste.
                ausschnitt = _nachschaerfen(
                    ausschnitt, format_breite / vorher if vorher else 1.0
                )
                pfad = ziel_stamm.with_name(f"{ziel_stamm.stem}-p{i + 1}.png")
                ausschnitt.save(pfad)
                teile.append(pfad)
    except Exception as exc:  # noqa: BLE001 - lieber ein Bild als gar keines
        log.warning("Panorama nicht zerschnitten (%s): %s", quelle.name, exc)
        return []

    log.info("Panorama %s in %s Stücke zerschnitten", quelle.name, len(teile))
    return teile


__all__ = ["ist_panorama", "stueckzahl", "zerschneide"]
