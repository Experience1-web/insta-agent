"""Echte Aufnahmen holen - und nur solche, die man auch nehmen darf.

Ein erzeugtes Bild zeigt, wie etwas aussehen könnte. Bei einem Fund ist
das die zweitbeste Lösung: Wer liest, dass 140 Münzen 1.800 Jahre
unberührt lagen, will die Münzen sehen und nicht eine Vorstellung davon.

Das Problem ist nicht das Finden, sondern das Dürfen. Die meisten Fotos
im Netz gehören jemandem, und ein Urheberrechtsverstoß kostet auf
Instagram im Wiederholungsfall das Konto - also genau das, was dieser
Betrieb sonst überall zu vermeiden versucht.

Wikimedia Commons löst das, weil dort die Lizenz strukturiert an der
Datei hängt und sich maschinell lesen lässt. Genommen wird nur, was
ausdrücklich auch gewerblich genutzt werden darf: gemeinfrei, CC0, CC BY,
CC BY-SA. Alles mit NC (nicht-kommerziell), ND (keine Bearbeitung) oder
ohne klare Angabe fällt durch - im Zweifel lieber ein gemaltes Bild als
ein geliehenes.

Die Namensnennung ist keine Höflichkeit, sondern die Bedingung. Sie wird
deshalb mitgeführt und gehört in die Bildunterschrift.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Wie lange wir insgesamt warten. Eine Bildsuche darf den Zyklus nicht
# aufhalten - lieber kein Foto als ein hängender Lauf.
GEDULD = 20.0

# Kleiner als das taugt nichts: Instagram zeigt 1080 Pixel breit, und ein
# hochskaliertes Bild sieht schlechter aus als ein gemaltes. Mit Rand zum
# Beschneiden - der Beitrag ist hochkant, die meisten Aufnahmen sind quer.
MINDESTBREITE = 1400

# So gross fragen wir an. Wikimedia rechnet die Vorschau auf Wunsch
# herunter, aber nie hoch: Was hier steht, ist die Obergrenze dessen, was
# wir bekommen koennen.
WUNSCHBREITE = 2400

# Dateien, die zwar frei sind, aber keinen Beitrag tragen: Wappen,
# Diagramme, Karten, Bildschirmfotos. Sie stehen bei fast jeder Suche
# weit oben, weil ihre Beschreibung genau die gesuchten Worte enthaelt.
UNBRAUCHBAR = (
    "logo",
    "icon",
    "coat of arms",
    "wappen",
    "diagram",
    "diagramm",
    "chart",
    "graph",
    "map of",
    "karte von",
    "screenshot",
    "flag of",
    "signature",
    "stub",
    "disambig",
)

# Was ausdrücklich auch gewerblich erlaubt ist. Die Liste ist bewusst
# knapp: Was hier nicht steht, wird nicht genommen, auch wenn es
# wahrscheinlich in Ordnung wäre.
ERLAUBT = (
    "cc0",
    "public domain",
    "pd-",
    "cc by 2.0",
    "cc by 2.5",
    "cc by 3.0",
    "cc by 4.0",
    "cc by-sa 2.0",
    "cc by-sa 2.5",
    "cc by-sa 3.0",
    "cc by-sa 4.0",
    "cc-by-sa",
    "cc-by-",
)

# Was auf jeden Fall ausscheidet, auch wenn oben etwas zu passen scheint.
# "CC BY-NC 4.0" enthält "cc by" - ohne diese Sperre käme es durch.
VERBOTEN = ("-nc", " nc", "noncommercial", "-nd", " nd", "noderiv", "fair use", "nonfree")


@dataclass(slots=True)
class Fundbild:
    """Eine Aufnahme, die genommen werden darf - mit der Pflichtangabe.

    Adresse und Datei sind zwei Felder und nicht eines. Ein `Path` ist
    kein Behälter für eine URL: Er normalisiert den doppelten
    Schrägstrich in "https://" weg, und was dann herauskommt, lässt sich
    weder abrufen noch wiedererkennen.
    """

    url: str
    """Woher das Bild kommt - solange es noch nicht geladen ist."""

    pfad: Path | None
    """Wo es liegt, sobald es geladen wurde."""

    lizenz: str
    urheber: str
    seite: str
    breite: int
    hoehe: int

    @property
    def nachweis(self) -> str:
        """Die Zeile, die unter dem Beitrag stehen muss."""
        wer = self.urheber or "unbekannt"
        return f"Bild: {wer} · {self.lizenz} · via Wikimedia Commons"


def _ohne_markup(text: str) -> str:
    """Commons liefert die Urhebernennung als HTML-Schnipsel."""
    ohne = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", ohne).strip()


def darf_genutzt_werden(lizenz: str) -> bool:
    """Ob diese Lizenz gewerbliche Nutzung und Bearbeitung erlaubt.

    Bearbeitung zählt, weil auf jedes Bild Schrift gelegt wird - unter
    einer ND-Lizenz wäre schon das nicht zulässig.
    """
    klein = (lizenz or "").casefold()
    if not klein or any(sperre in klein for sperre in VERBOTEN):
        return False
    return any(erlaubt in klein for erlaubt in ERLAUBT)


def _treffer(daten: dict) -> list[dict]:
    seiten = (daten.get("query") or {}).get("pages") or {}
    return list(seiten.values()) if isinstance(seiten, dict) else list(seiten)


def suchbegriffe(suchwort: str) -> list[str]:
    """Derselbe Fund, vom Genauen zum Allgemeinen.

    Der Grund, warum die Bildsuche bisher fast immer leer ausging: Die
    Stoffsuche liefert ein Suchwort wie "Exoplanet WASP-121b Atmosphaere
    Eisenregen". Danach gibt es in keinem Archiv ein Foto - den Planeten
    hat nie jemand fotografiert.

    Ein Bild von einem Exoplaneten gibt es aber sehr wohl. Also wird
    nicht einmal gesucht, sondern mehrfach: erst genau, dann immer
    weiter gefasst, bis etwas kommt. Das letzte Wort faellt zuerst weg,
    weil vorne meist der Oberbegriff steht.
    """
    worte = [w for w in re.split(r"[\s,;/]+", (suchwort or "").strip()) if w]
    if not worte:
        return []
    versuche: list[str] = []
    for ende in range(len(worte), 0, -1):
        begriff = " ".join(worte[:ende])
        if begriff not in versuche:
            versuche.append(begriff)
    # Mehr als vier Anlaeufe kosten mehr Zeit, als sie einbringen.
    return versuche[:4]


def _taugt_der_titel(titel: str) -> bool:
    klein = titel.casefold()
    return not any(schrott in klein for schrott in UNBRAUCHBAR)


def _bewerte(info: dict, seite: dict) -> Fundbild | None:
    """Macht aus einem Treffer ein Fundbild - oder None, wenn er durchfaellt."""
    meta = info.get("extmetadata") or {}
    lizenz = (meta.get("LicenseShortName") or {}).get("value", "")
    if not darf_genutzt_werden(lizenz):
        log.debug("Bild verworfen, Lizenz %r", lizenz)
        return None
    titel = str(seite.get("title", ""))
    if not _taugt_der_titel(titel):
        return None
    breite = int(info.get("thumbwidth") or info.get("width") or 0)
    hoehe = int(info.get("thumbheight") or info.get("height") or 0)
    if breite < MINDESTBREITE:
        return None
    return Fundbild(
        url=str(info.get("thumburl") or info.get("url") or ""),
        pfad=None,
        lizenz=lizenz,
        urheber=_ohne_markup((meta.get("Artist") or {}).get("value", "")),
        seite=titel,
        breite=breite,
        hoehe=hoehe,
    )


def _frage_commons(
    begriff: str, client: httpx.Client, treffer: int
) -> list[Fundbild]:
    try:
        antwort = client.get(
            COMMONS_API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:bitmap {begriff}",
                "gsrnamespace": "6",
                "gsrlimit": str(treffer),
                "prop": "imageinfo",
                "iiprop": "url|size|extmetadata",
                "iiurlwidth": str(WUNSCHBREITE),
            },
            headers={"User-Agent": "insta-agent/1.0 (Bildsuche fuer eigene Beitraege)"},
        )
        antwort.raise_for_status()
        daten = antwort.json()
    except Exception as exc:  # noqa: BLE001 - ohne Foto wird eben gemalt
        log.info("Bildsuche fehlgeschlagen (%r): %s", begriff, exc)
        return []

    gefunden: list[Fundbild] = []
    for seite in _treffer(daten):
        for info in seite.get("imageinfo") or []:
            if (bild := _bewerte(info, seite)) is not None:
                gefunden.append(bild)
    return gefunden


def suche_bild(
    suchwort: str, *, client: httpx.Client | None = None, treffer: int = 12
) -> Fundbild | None:
    """Sucht bei Wikimedia Commons die beste brauchbare freie Aufnahme.

    Gibt None zurück, wenn nichts passt - das ist kein Fehler, dann wird
    gemalt. Nur ist es seltener geworden: Gesucht wird in mehreren
    Anlaeufen vom Genauen zum Allgemeinen, und genommen wird die groesste
    Aufnahme des ersten Anlaufs, der etwas bringt - nicht die erste.

    Der Unterschied ist nicht klein: "die erste" hiess bisher "die, die
    Wikimedias Volltextsuche zufaellig oben hatte", und die ist oft
    knapp ueber der Mindestgroesse.

    Das Bild wird hier noch nicht geladen, nur ausgewählt: `pfad` bleibt
    leer, bis `hole_bild` es abholt.
    """
    eigener = client is None
    client = client or httpx.Client(timeout=GEDULD, follow_redirects=True)
    try:
        for begriff in suchbegriffe(suchwort):
            kandidaten = _frage_commons(begriff, client, treffer)
            if not kandidaten:
                continue
            beste = max(kandidaten, key=lambda b: b.breite * b.hoehe)
            log.info(
                "Bildsuche %r: %s Treffer, genommen %s (%sx%s)",
                begriff,
                len(kandidaten),
                beste.seite,
                beste.breite,
                beste.hoehe,
            )
            return beste
    finally:
        if eigener:
            client.close()
    return None


def hole_bild(bild: Fundbild, ziel: Path, *, client: httpx.Client | None = None) -> Fundbild | None:
    """Lädt die ausgewählte Aufnahme herunter. None, wenn es nicht klappt."""
    quelle = bild.url
    if not quelle.startswith("http"):
        return None

    eigener = client is None
    client = client or httpx.Client(timeout=GEDULD, follow_redirects=True)
    try:
        antwort = client.get(
            quelle, headers={"User-Agent": "insta-agent/1.0 (Bildsuche fuer eigene Beitraege)"}
        )
        antwort.raise_for_status()
        inhalt = antwort.content
    except Exception as exc:  # noqa: BLE001 - ohne Foto wird eben gemalt
        log.info("Bild nicht geladen: %s", exc)
        return None
    finally:
        if eigener:
            client.close()

    if not inhalt:
        return None
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(inhalt)
    bild.pfad = ziel
    return bild


def finde_und_hole(suchwort: str, ziel: Path, *, client: httpx.Client | None = None):
    """Beides in einem: suchen und laden. None heisst - es wird gemalt."""
    gefunden = suche_bild(suchwort, client=client)
    if gefunden is None:
        return None
    geladen = hole_bild(gefunden, ziel, client=client)
    if geladen is not None:
        log.info("Echtes Bild gefunden: %s (%s)", geladen.seite, geladen.lizenz)
    return geladen


__all__ = [
    "Fundbild",
    "darf_genutzt_werden",
    "finde_und_hole",
    "hole_bild",
    "suche_bild",
    "suchbegriffe",
]
