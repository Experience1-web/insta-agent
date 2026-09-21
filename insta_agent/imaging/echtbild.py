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
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# Wie wir uns bei den Archiven vorstellen - und das ist keine Formalie.
#
# Wikimedia verlangt eine Kennung, aus der hervorgeht, wer da anfragt und
# wo man sich beschweren kann. Wer ohne kommt oder nur einen Programmnamen
# nennt, bekommt 403 Forbidden - von der Schnittstelle und vom Bildserver
# gleichermassen. Genau daran ist die Suche beim ersten echten Versuch
# gescheitert, und die Fehlermeldung sah aus, als sei das Bild gesperrt.
#
# Als Kontakt steht die Adresse des Quelltexts da, nicht die des
# Betreibers: Sie ist oeffentlich, dauerhaft und fuehrt zu jemandem, der
# etwas aendern kann. Wer seine eigene Anschrift nennen will, setzt
# BILD_KONTAKT - eine E-Mail-Adresse gehoert niemandem ungefragt in einen
# Kopfzeileneintrag, der an jeden Server geht.
HERKUNFT = "https://github.com/Experience1-web/insta-agent"


def kennung() -> str:
    """Die Zeile, mit der wir uns bei jedem Archiv melden."""
    import os

    kontakt = (os.getenv("BILD_KONTAKT") or "").strip() or HERKUNFT
    return f"insta-agent/1.0 ({kontakt}) python-httpx"


COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Die zweite Quelle. Openverse gehoert zu WordPress und wird zusammen mit
# Creative Commons betrieben; es durchsucht Flickr, Museen, Archive und
# Wikimedia in einem - und filtert dabei selbst nach Lizenz.
#
# Warum ueberhaupt eine zweite: Commons ist gut bei allem, was in einer
# Enzyklopaedie steht - Fundorte, Gegenstaende, Arten. Es ist duenn bei
# allem, was ein Fotograf aufgenommen hat, ohne dass ein Artikel dazu
# existiert. Genau das sind die Bilder, die einen Beitrag tragen.
#
# Kein Schluessel noetig. Ohne einen gelten engere Grenzen, aber ein
# Beitrag am Tag liegt weit darunter.
OPENVERSE_API = "https://api.openverse.org/v1/images/"

# Was Openverse ausliefern darf, damit wir es nehmen duerfen. Dieselbe
# Regel wie bei Commons: gewerblich erlaubt und bearbeitbar, sonst nicht.
OPENVERSE_LIZENZEN = "cc0,pdm,by,by-sa"

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
    # Weitere Adressen desselben Bildes. Openverse verweist auf das
    # Original beim Anbieter - Flickr, ein Museum, ein Archiv -, und
    # nicht jeder davon laesst sich einfach abrufen. Dann hilft die
    # Fassung, die Openverse selbst vorhaelt.
    ersatz: list[str] = field(default_factory=list)
    # Warum es nicht geklappt hat, falls es nicht geklappt hat.
    grund: str = ""

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


# Die Themenfelder des Accounts, uebersetzt in das, womit ein Bildarchiv
# etwas anfangen kann. Die letzte Rettung, wenn alles Genauere nichts
# bringt: Ein Bild aus dem richtigen Feld schlaegt ein gemaltes Bild,
# weil es echt ist - und darum geht es hier.
GEBIETSWORTE = {
    "archäolog": "archaeological excavation site",
    "archaeolog": "archaeological excavation site",
    "ausgegraben": "archaeological excavation site",
    "grabung": "archaeological excavation site",
    "artenfund": "newly described species specimen",
    "biolog": "wildlife photograph specimen",
    "tiefsee": "deep sea underwater photograph",
    "paläont": "fossil specimen museum",
    "palaeont": "fossil specimen museum",
    "medizin": "medical research laboratory",
    "zell": "microscopy cell image",
    "raumfahrt": "spacecraft nasa photograph",
    "astronom": "astronomical observation telescope image",
    "weltall": "astronomical observation telescope image",
    "exoplanet": "exoplanet artist impression nasa",
    "technik": "laboratory research equipment",
    "material": "materials science laboratory",
    "polar": "polar expedition photograph",
}


def suchworte_fuer(fund) -> list[str]:
    """Womit nach einer echten Aufnahme dieses Fundes gesucht wird.

    Bisher war das ein einziges Feld, und war es leer, wurde gar nicht
    gesucht - dann entstand ein gemaltes Bild, obwohl womoeglich ein Foto
    dalag. Bei einem Account ueber tatsaechlich Geschehenes ist das der
    teuerste Verzicht ueberhaupt: Wer liest, dass etwas gefunden wurde,
    will es sehen, und ein gemaltes Bild zeigt nur, wie es aussehen
    koennte.

    Also mehrere Anlaeufe, vom Genauesten zum Allgemeinsten, und der
    letzte greift immer: das Themenfeld selbst.
    """
    if fund is None:
        return []

    worte: list[str] = []

    def dazu(text: str) -> None:
        sauber = (text or "").strip()
        if sauber and sauber not in worte:
            worte.append(sauber)

    # 1. Was die Stoffsuche ausdruecklich dafuer vorgesehen hat.
    dazu(getattr(fund, "bildsuche", ""))

    # 2. Der Titel des Fundes. Deutsch bringt weniger Treffer als
    #    Englisch, aber Eigennamen und Fundorte stehen in jeder Sprache
    #    gleich da - und genau die findet ein Archiv.
    dazu(getattr(fund, "titel", ""))

    # 3. Das Themenfeld, uebersetzt. Die letzte Rettung.
    gebiet = (getattr(fund, "gebiet", "") or "").casefold()
    for schluessel, begriff in GEBIETSWORTE.items():
        if schluessel in gebiet:
            dazu(begriff)
            break

    return worte


def guete(breite: int, hoehe: int) -> float:
    """Wie gut sich dieses Bild fuer einen Beitrag eignet, 0 bis ungefaehr 2.

    "Das groesste nehmen" war das falsche Kriterium, und man sieht sofort
    warum: Bei "rare bird" gewann eine Tafel von 2400 x 5317 - kein Foto,
    sondern ein hochkant gescanntes Blatt mit vielen Arten untereinander.
    Auf 4:5 beschnitten saehe man davon einen Streifen.

    Es zaehlt also zuerst die Form, dann die Groesse:

    - Ein sehr breites Bild ist das Beste, was passieren kann: Daraus
      wird ein Karussell, durch das man wandert.
    - Ein Bild nahe am Beitragsformat ist gut.
    - Ein sehr hohes ist schlecht. Es laesst sich nicht sinnvoll
      beschneiden und fast nie als Ganzes zeigen.

    Die Groesse geht nur noch schwach ein. Ab etwa 2000 Pixel ist ein
    Bild fuer Instagram gut genug, und doppelt so viele Pixel machen es
    nicht doppelt so brauchbar.
    """
    if breite <= 0 or hoehe <= 0:
        return 0.0
    verhaeltnis = breite / hoehe

    # Die Grenzen sind keine runden Zahlen, sondern Formate: 0,8 ist der
    # Beitrag, 0,5625 ist 9:16, 2,2 ist die Schwelle zum Panorama.
    if verhaeltnis >= 2.2:
        form = 1.6          # Panorama - daraus wird ein Karussell
    elif verhaeltnis >= 1.6:
        form = 1.0          # gewoehnliches Querformat
    elif verhaeltnis >= 0.6:
        form = 1.3          # nahe am Beitragsformat
    elif verhaeltnis >= 0.5:
        form = 0.9          # hochkant wie eine Story, noch brauchbar
    else:
        form = 0.25         # eine Tafel, kein Foto

    # Ab 2000 Pixel bringt mehr kaum noch etwas. Ganz zu deckeln waere
    # aber auch falsch: Dann entscheidet bei zwei brauchbaren Bildern der
    # Zufall, statt dass das schaerfere gewinnt. Also eine flache Kurve -
    # doppelte Kantenlaenge bringt rund ein Zehntel mehr.
    groesse = min(1.3, (max(breite, hoehe) / 2000) ** 0.15)
    return form * (0.75 + 0.25 * groesse)


def rangfaktor(platz: int) -> float:
    """Wie stark ein Treffer dadurch verliert, dass er weiter hinten steht.

    Der Fehler, den das behebt, war unsichtbar, bis man das Ergebnis las:
    Bei "deep sea creature" gewann eine Aufnahme mit dem Titel "2018 NYEC
    in Dalian (Self-participation; Deep Sea Legend following Fireworks)" -
    ein Feuerwerk, das zufaellig "Deep Sea" im Namen hat.

    Der Grund: Aus zwoelf Treffern wurde der mit der besten Form genommen,
    egal an welcher Stelle er stand. Damit war die Rangfolge der
    Suchmaschine weggeworfen - und die ist das Einzige, was ueberhaupt
    etwas darueber weiss, ob ein Bild zum Thema gehoert. Form und
    Aufloesung wissen das nicht.

    Die Steigung ist ausprobiert, nicht geraten. Bei 0,15 gilt beides:
    Unter aehnlich brauchbaren Bildern gewinnt das vorderste, weil es
    wahrscheinlicher zum Thema gehoert. Eine unbrauchbare Tafel auf Platz
    eins verliert trotzdem noch gegen ein gutes Foto auf Platz acht.
    """
    return 1.0 / (1.0 + 0.15 * max(0, platz))


def _taugt_der_titel(titel: str) -> bool:
    klein = titel.casefold()
    return not any(schrott in klein for schrott in UNBRAUCHBAR)


def _bewerte(info: dict, seite: dict, bilanz: "Bilanz | None" = None) -> Fundbild | None:
    """Macht aus einem Treffer ein Fundbild - oder None, wenn er durchfaellt."""
    meta = info.get("extmetadata") or {}
    lizenz = (meta.get("LicenseShortName") or {}).get("value", "")
    if not darf_genutzt_werden(lizenz):
        log.debug("Bild verworfen, Lizenz %r", lizenz)
        if bilanz:
            bilanz.lizenz += 1
        return None
    titel = str(seite.get("title", ""))
    if not _taugt_der_titel(titel):
        if bilanz:
            bilanz.titel += 1
        return None
    breite = int(info.get("thumbwidth") or info.get("width") or 0)
    hoehe = int(info.get("thumbheight") or info.get("height") or 0)
    if breite < MINDESTBREITE:
        if bilanz:
            bilanz.zu_klein += 1
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


@dataclass(slots=True)
class Bilanz:
    """Was eine Suche gebracht hat - und was sie weggeworfen hat.

    Ohne das steht am Ende nur "nichts gefunden", und man weiss nicht,
    ob das Archiv nichts hatte oder ob die eigenen Filter alles
    aussortiert haben. Das ist ein Unterschied wie Tag und Nacht: Im
    einen Fall braucht es ein anderes Suchwort, im anderen eine andere
    Schwelle.
    """

    roh: int = 0
    lizenz: int = 0
    titel: int = 0
    zu_klein: int = 0
    genommen: int = 0
    fehler: str = ""

    def __str__(self) -> str:
        if self.fehler:
            return f"Fehler: {self.fehler}"
        if not self.roh:
            return "0 Treffer"
        verworfen = []
        if self.lizenz:
            verworfen.append(f"{self.lizenz}x Lizenz")
        if self.titel:
            verworfen.append(f"{self.titel}x Art")
        if self.zu_klein:
            verworfen.append(f"{self.zu_klein}x zu klein")
        rest = f" ({', '.join(verworfen)})" if verworfen else ""
        return f"{self.roh} Treffer, {self.genommen} brauchbar{rest}"


def _frage_commons(
    begriff: str, client: httpx.Client, treffer: int, bilanz: Bilanz | None = None
) -> list[Fundbild]:
    bilanz = bilanz if bilanz is not None else Bilanz()
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
            headers={"User-Agent": kennung(), "Api-User-Agent": kennung()},
        )
        antwort.raise_for_status()
        daten = antwort.json()
    except Exception as exc:  # noqa: BLE001 - ohne Foto wird eben gemalt
        log.info("Bildsuche fehlgeschlagen (%r): %s", begriff, exc)
        bilanz.fehler = f"{type(exc).__name__}: {exc}"
        return []

    gefunden: list[Fundbild] = []
    for seite in _treffer(daten):
        for info in seite.get("imageinfo") or []:
            bilanz.roh += 1
            if (bild := _bewerte(info, seite, bilanz)) is not None:
                gefunden.append(bild)
                bilanz.genommen += 1
    return gefunden


def _frage_openverse(
    begriff: str, client: httpx.Client, treffer: int, bilanz: Bilanz | None = None
) -> list[Fundbild]:
    """Dieselbe Suche bei Openverse. Leer heisst: nichts Brauchbares.

    Die Lizenzpruefung passiert zweimal: Openverse filtert schon serverseitig,
    und was zurueckkommt, laeuft trotzdem durch dieselbe Pruefung wie ein
    Commons-Treffer. Ein Dienst, der sich irrt, soll uns nicht in ein
    Urheberrechtsproblem ziehen.
    """
    try:
        antwort = client.get(
            OPENVERSE_API,
            params={
                "q": begriff,
                "license": OPENVERSE_LIZENZEN,
                "page_size": str(treffer),
                # Nur was gross genug ist - kleiner taugt fuer Instagram nicht.
                "size": "large",
                "mature": "false",
            },
            headers={"User-Agent": kennung(), "Api-User-Agent": kennung()},
        )
        antwort.raise_for_status()
        daten = antwort.json()
    except Exception as exc:  # noqa: BLE001 - dann bleibt es bei Commons
        log.info("Openverse fehlgeschlagen (%r): %s", begriff, exc)
        if bilanz is not None:
            bilanz.fehler = f"{type(exc).__name__}: {exc}"
        return []

    bilanz = bilanz if bilanz is not None else Bilanz()
    gefunden: list[Fundbild] = []
    for eintrag in daten.get("results") or []:
        if not isinstance(eintrag, dict):
            continue
        bilanz.roh += 1
        lizenz = str(eintrag.get("license") or "")
        version = str(eintrag.get("license_version") or "")
        # "by" + "4.0" ergibt "CC BY 4.0" - so, wie die Pruefung es kennt.
        lesbar = f"CC {lizenz.upper()} {version}".strip() if lizenz != "pdm" else "Public domain"
        if not darf_genutzt_werden(lesbar):
            bilanz.lizenz += 1
            continue

        titel = str(eintrag.get("title") or "")
        if not _taugt_der_titel(titel):
            bilanz.titel += 1
            continue

        breite = int(eintrag.get("width") or 0)
        hoehe = int(eintrag.get("height") or 0)
        if breite < MINDESTBREITE:
            bilanz.zu_klein += 1
            continue

        url = str(eintrag.get("url") or "")
        if not url.startswith("http"):
            bilanz.titel += 1
            continue

        bilanz.genommen += 1

        # Die Adressen, unter denen dasselbe Bild zu haben ist, in der
        # Reihenfolge der Qualitaet: das Original beim Anbieter zuerst,
        # dann die Fassungen, die Openverse selbst ausliefert.
        ausweich = [
            str(eintrag.get("thumbnail") or ""),
            f"{OPENVERSE_API}{eintrag.get('id')}/thumb/" if eintrag.get("id") else "",
        ]

        gefunden.append(
            Fundbild(
                url=url,
                pfad=None,
                lizenz=lesbar,
                urheber=_ohne_markup(str(eintrag.get("creator") or "")),
                seite=str(eintrag.get("foreign_landing_url") or titel),
                breite=breite,
                hoehe=hoehe,
                # Ohne Doppelte: `thumbnail` ist oft schon genau die
                # Adresse, die wir sonst selbst zusammensetzen wuerden.
                ersatz=list(dict.fromkeys(a for a in ausweich if a and a != url)),
            )
        )
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
            # Commons zuerst: Dort steht oft genau die Aufnahme, die zu
            # der Veroeffentlichung gehoert. Openverse danach, weil es
            # breiter ist, aber seltener die Sache selbst zeigt.
            kandidaten = _frage_commons(begriff, client, treffer)
            if not kandidaten:
                kandidaten = _frage_openverse(begriff, client, treffer)
            if not kandidaten:
                continue
            # Rang mal Eignung: Das Archiv weiss, was zum Thema gehoert,
            # wir wissen, was sich als Beitragsbild macht. Beides allein
            # geht daneben.
            geordnet = sorted(
                enumerate(kandidaten),
                key=lambda p: guete(p[1].breite, p[1].hoehe) * rangfaktor(p[0]),
                reverse=True,
            )
            beste = geordnet[0][1]
            log.info(
                "Bildsuche %r: %s Treffer, genommen Platz %s: %s (%sx%s)",
                begriff,
                len(kandidaten),
                geordnet[0][0] + 1,
                beste.seite,
                beste.breite,
                beste.hoehe,
            )
            return beste
    finally:
        if eigener:
            client.close()
    return None


def suche_bilder(
    suchwort: str, *, client: httpx.Client | None = None, treffer: int = 12
) -> list[Fundbild]:
    """Alle brauchbaren Treffer, das beste zuerst.

    Gebraucht, weil sich erst am heruntergeladenen Bild feststellen
    laesst, ob es eine Fotografie ist oder eine Zeichnung auf weissem
    Grund. Ein einzelner Treffer waere dann eine Sackgasse: Faellt er
    durch, wird gemalt, obwohl der naechste gut gewesen waere.
    """
    eigener = client is None
    client = client or httpx.Client(timeout=GEDULD, follow_redirects=True)
    try:
        for begriff in suchbegriffe(suchwort):
            kandidaten = _frage_commons(begriff, client, treffer)
            if not kandidaten:
                kandidaten = _frage_openverse(begriff, client, treffer)
            if not kandidaten:
                continue
            return [
                bild
                for _platz, bild in sorted(
                    enumerate(kandidaten),
                    key=lambda p: guete(p[1].breite, p[1].hoehe) * rangfaktor(p[0]),
                    reverse=True,
                )
            ]
    finally:
        if eigener:
            client.close()
    return []


def _kopfzeilen(adresse: str) -> dict[str, str]:
    """Womit wir ein einzelnes Bild abholen.

    Der Verweis auf die Herkunftsseite geht nur an Wikimedia, wo er
    erwartet wird. Ihn an jeden fremden Server zu schicken waere eine
    Behauptung ueber etwas, das gar nicht stattgefunden hat.
    """
    kopf = {"User-Agent": kennung(), "Accept": "image/*,*/*;q=0.8"}
    if "wikimedia.org" in adresse or "wikipedia.org" in adresse:
        kopf["Referer"] = "https://commons.wikimedia.org/"
    return kopf


def _ist_wirklich_ein_bild(inhalt: bytes) -> bool:
    """Ob das Heruntergeladene ein Bild ist - und keine Fehlerseite.

    Wird eine Aufnahme vom Anbieter abgelehnt, kommt oft trotzdem ein
    200 zurueck, nur mit HTML darin. Ohne diese Pruefung landet eine
    Fehlerseite als Beitragsbild auf der Platte und faellt erst beim
    Beschriften auf.
    """
    # Die eigentliche Arbeit machen die Kennbytes weiter unten. Die
    # Laengengrenze faengt nur den Fall ab, dass ueberhaupt nichts kam -
    # sie darf nicht so hoch liegen, dass ein kleines, aber echtes Bild
    # daran scheitert.
    if len(inhalt) < 64:
        return False
    anfaenge = (
        b"\xff\xd8\xff",      # JPEG
        b"\x89PNG\r\n\x1a\n",  # PNG
        b"GIF8",              # GIF
        b"RIFF",              # WEBP
    )
    return inhalt.startswith(anfaenge)


def hole_bild(
    bild: Fundbild, ziel: Path, *, client: httpx.Client | None = None
) -> Fundbild | None:
    """Lädt die ausgewählte Aufnahme herunter. None, wenn es nicht klappt.

    Mehrere Adressen, weil eine nicht reicht: Openverse verweist auf das
    Original beim Anbieter, und Flickr oder ein Museumsserver lehnen eine
    fremde Anfrage gern ab. Dann wird die Fassung genommen, die Openverse
    selbst vorhaelt.

    Der Grund eines Fehlschlags landet in `bild.grund` - "nicht ladbar"
    allein sagt niemandem, ob es am Netz lag, an einer Absage oder daran,
    dass eine HTML-Seite kam statt eines Bildes.
    """
    adressen = [a for a in [bild.url, *bild.ersatz] if a and a.startswith("http")]
    if not adressen:
        bild.grund = "keine brauchbare Adresse"
        return None

    eigener = client is None
    client = client or httpx.Client(timeout=GEDULD, follow_redirects=True)
    gruende: list[str] = []
    try:
        for adresse in adressen:
            try:
                antwort = client.get(
                    adresse,
                    headers=_kopfzeilen(adresse),
                )
            except Exception as exc:  # noqa: BLE001 - die naechste Adresse
                gruende.append(f"{type(exc).__name__}")
                continue

            if antwort.status_code >= 400:
                gruende.append(f"HTTP {antwort.status_code}")
                continue

            inhalt = antwort.content
            if not _ist_wirklich_ein_bild(inhalt):
                typ = antwort.headers.get("content-type", "?")
                gruende.append(f"kein Bild, sondern {typ} ({len(inhalt)} Byte)")
                continue

            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_bytes(inhalt)
            bild.pfad = ziel
            bild.grund = ""
            return bild
    finally:
        if eigener:
            client.close()

    bild.grund = "; ".join(gruende) or "unbekannt"
    log.info("Bild nicht geladen (%s): %s", bild.seite, bild.grund)
    return None


def finde_und_hole(
    suchwort: str, ziel: Path, *, client: httpx.Client | None = None, versuche: int = 4
):
    """Suchen, laden und nachsehen, ob es wirklich eine Fotografie ist.

    Der Reihe nach, denn erst am geladenen Bild zeigt sich, was es ist.
    Bei "deep sea creature" gewann eine Datei namens "Humpback
    anglerfish.png" - frei, gross, gut geschnitten und trotzdem eine
    wissenschaftliche Zeichnung auf Weiss. Frueher war damit Schluss und
    es wurde gemalt; jetzt kommt der naechste Treffer dran.

    None heisst: Von den ersten paar Treffern war keiner brauchbar.
    """
    from .fotoprobe import wirkt_wie_foto

    kandidaten = suche_bilder(suchwort, client=client)
    for bild in kandidaten[: max(1, versuche)]:
        geladen = hole_bild(bild, ziel, client=client)
        if geladen is None:
            continue
        taugt, grund = wirkt_wie_foto(ziel)
        if not taugt:
            log.info("Verworfen (%s): %s", bild.seite, grund)
            bild.grund = grund
            continue
        log.info("Echtes Bild gefunden: %s (%s)", geladen.seite, geladen.lizenz)
        return geladen
    return None


__all__ = [
    "Fundbild",
    "darf_genutzt_werden",
    "finde_und_hole",
    "hole_bild",
    "suche_bild",
    "suche_bilder",
    "suchbegriffe",
    "suchworte_fuer",
    "Bilanz",
    "kennung",
    "guete",
    "rangfaktor",
]
