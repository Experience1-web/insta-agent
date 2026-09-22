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

# Und so hoch. Die Hoehe war bisher voellig ungeprueft, und genau daran
# ist es gescheitert: Eine Aufnahme von 1804 x 1176 kam durch, weil sie
# breit genug war. Im Beitragsformat bleiben davon 940 Pixel Breite -
# die muessen auf 1080 hochgerechnet werden, und das sieht man.
#
# 1200 statt der noetigen 1350: Die letzten Prozent Hochrechnung sieht
# niemand, und jedes Bild, das hier ausscheidet, ist eines weniger zur
# Auswahl. Wirklich entschieden wird ohnehin ueber die Guete.
MINDESTHOEHE = 1200

# So gross fragen wir an. Wikimedia rechnet die Vorschau auf Wunsch
# herunter, aber nie hoch: Was hier steht, ist die Obergrenze dessen, was
# wir bekommen koennen.
#
# Lieber zu gross als zu knapp. Herunterrechnen kostet nichts und macht
# ein Bild eher schaerfer; hochrechnen laesst sich nicht rueckgaengig
# machen. Der Unterschied sind ein paar hundert Kilobyte einmal am Tag.
WUNSCHBREITE = 3200

# Worauf ein Bild am Ende landet: 1080 Pixel breit, im Verhaeltnis 4:5.
# Alles, was danach noch hochgerechnet werden muss, wird unscharf - und
# das ist der Grund, warum die Guete danach rechnet und nicht nach der
# rohen Pixelzahl.
ZIELBREITE = 1080
BEITRAGSVERHAELTNIS = 1080 / 1350

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
        """Die Zeile, die unter dem Beitrag stehen muss.

        Zwei Dinge, die vorher falsch waren und in jeder Bildunterschrift
        standen:

        "Bild: unbekannt" war unnoetig. Bei gemeinfrei und CC0 verlangt
        niemand eine Namensnennung - sie ist der Grund, warum diese
        Lizenzen ueberhaupt gewaehlt wurden. Wo kein Name steht, bleibt
        die Zeile eben kuerzer.

        Und "via Wikimedia Commons" stimmte nur bei der Haelfte. Ueber
        Openverse kommen Bilder von Flickr, aus Museen und Archiven - die
        dort als Wikimedia auszugeben, waere eine falsche Angabe an genau
        der Stelle, an der es auf Richtigkeit ankommt.
        """
        teile = ["Bild:"]
        wer = (self.urheber or "").strip()
        if wer:
            teile.append(f"{wer} ·")
        teile.append(self.lizenz)
        if quelle := self.quellenname:
            teile.append(f"· via {quelle}")
        return " ".join(teile)

    @property
    def quellenname(self) -> str:
        """Woher das Bild stammt, lesbar - aus der Adresse der Fundstelle."""
        seite = self.seite or ""
        if "commons.wikimedia" in seite or seite.startswith("File:"):
            return "Wikimedia Commons"
        treffer = re.search(r"https?://(?:www\.)?([^/]+)", seite)
        if not treffer:
            return ""
        rechner = treffer.group(1)
        bekannt = {
            "flickr.com": "Flickr",
            "live.staticflickr.com": "Flickr",
            "openverse.org": "Openverse",
            "smithsonianmag.com": "Smithsonian",
            "si.edu": "Smithsonian",
            "nasa.gov": "NASA",
            "esa.int": "ESA",
            "noaa.gov": "NOAA",
        }
        for endung, name in bekannt.items():
            if rechner.endswith(endung):
                return name
        return rechner


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


def nutzmasse(
    breite: int, hoehe: int, verhaeltnis: float = BEITRAGSVERHAELTNIS
) -> tuple[int, int]:
    """Was von einem Bild uebrig bleibt, wenn es aufs Beitragsformat kommt.

    Instagram nimmt keine beliebigen Seitenverhaeltnisse an, also wird
    mittig beschnitten. Von einer breiten Aufnahme bleibt dabei ein
    hochkanter Ausschnitt - und der ist erheblich schmaler als das
    Original. Genau diese Zahl zaehlt, nicht die des Originals.

    Beispiel, und es ist der Fall, an dem es aufgefallen ist: 2400 x 1565
    klingt nach reichlich. Uebrig bleiben 1252 x 1565 - immer noch genug
    fuer 1080, aber eben nicht mehr weit davon entfernt. Bei 1600 x 900
    waeren es 720 x 900, und die muessten um die Haelfte hochgerechnet
    werden.

    Ein Panorama wird nicht beschnitten, sondern zerschnitten - dort gilt
    dieselbe Rechnung, weil jedes Teilstueck die volle Hoehe und daraus
    seine Breite bekommt.
    """
    if breite <= 0 or hoehe <= 0 or verhaeltnis <= 0:
        return (0, 0)
    nutz_b = min(breite, hoehe * verhaeltnis)
    nutz_h = min(hoehe, breite / verhaeltnis)
    return (int(nutz_b), int(nutz_h))


def massfaktor(
    breite: int, hoehe: int, verhaeltnis: float = BEITRAGSVERHAELTNIS
) -> float:
    """Wie oft die Zielbreite im nutzbaren Ausschnitt steckt.

    Ueber 1 heisst: wird verkleinert, das Bild bleibt scharf. Unter 1
    heisst: muss hochgerechnet werden, und das sieht man.
    """
    nutz_b, _ = nutzmasse(breite, hoehe, verhaeltnis)
    return nutz_b / ZIELBREITE if nutz_b else 0.0


def guete(
    breite: int, hoehe: int, *, zielverhaeltnis: float = BEITRAGSVERHAELTNIS
) -> float:
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

    # Die Groesse zaehlt nicht mehr nach der langen Kante - das war
    # falsch, denn die lange Kante ist genau die, die der Zuschnitt
    # wegnimmt. Gezaehlt wird, was danach uebrig bleibt.
    mass = massfaktor(breite, hoehe, zielverhaeltnis)
    if mass < 1.0:
        # Muss hochgerechnet werden. Quadratisch, damit es wirklich
        # wehtut: Bei 0,8 bleiben 64 Prozent, bei der Haelfte ein
        # Viertel. Ein solches Bild soll nur gewinnen, wenn nichts
        # Besseres da ist.
        return form * mass * mass
    # Darueber bringt mehr kaum noch etwas - ein Bild, das sowieso
    # verkleinert wird, ist scharf. Die flache Kurve entscheidet nur
    # noch zwischen zwei ohnehin brauchbaren Funden.
    return form * (0.75 + 0.25 * min(1.3, mass ** 0.25))


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

    Die Steigung ist ausprobiert, nicht geraten - und einmal nachgezogen.
    Mit 0,15 stand dasselbe Feuerwerk ein zweites Mal im Ergebnis: Eine
    echte Aufnahme vom Meeresgrund auf Platz zwei kam auf 0,77, das
    Feuerwerk auf Platz drei auf 0,70. Zu knapp fuer einen Unterschied,
    der so gross ist.

    Mit 0,30 sind es 0,68 gegen 0,57, und die Eigenschaft, wegen der die
    Steigung flach war, bleibt erhalten: Eine unbrauchbare gescannte
    Tafel auf Platz eins kommt auf 0,26 und verliert weiterhin gegen ein
    gutes Foto auf Platz acht mit 0,42.

    Mehr ginge nicht mehr gut. Die Rangfolge des Archivs ist ein
    Anhaltspunkt und kein Urteil - wer ihr ganz folgt, nimmt wieder das
    erste, was die Volltextsuche oben hatte.
    """
    return 1.0 / (1.0 + 0.30 * max(0, platz))


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
    if breite < MINDESTBREITE or hoehe < MINDESTHOEHE:
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
        if breite < MINDESTBREITE or hoehe < MINDESTHOEHE:
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
    suchwort: str,
    *,
    client: httpx.Client | None = None,
    treffer: int = 12,
    zielverhaeltnis: float = BEITRAGSVERHAELTNIS,
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
                key=lambda p: guete(
                    p[1].breite, p[1].hoehe, zielverhaeltnis=zielverhaeltnis
                )
                * rangfaktor(p[0]),
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
    suchwort: str,
    *,
    client: httpx.Client | None = None,
    treffer: int = 12,
    zielverhaeltnis: float = BEITRAGSVERHAELTNIS,
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
                    key=lambda p: guete(
                    p[1].breite, p[1].hoehe, zielverhaeltnis=zielverhaeltnis
                )
                * rangfaktor(p[0]),
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


def _uebernimm_echte_masse(bild: Fundbild, ziel: Path) -> None:
    """Die Masse der geladenen Datei eintragen statt der gemeldeten.

    Das ist kein Feinschliff, sondern eine Luecke, durch die genau das
    gefallen ist, was hinterher unscharf aussah: Gemeldet waren 2400 x
    2248, auf der Platte lagen 1804 x 1176. Geladen wurde naemlich nicht
    die Adresse, nach deren Massen ausgewaehlt wurde, sondern eine
    Ersatzadresse - und die haelt oft eine kleinere Fassung vor.

    Aus 1176 Pixeln Hoehe werden im Beitragsformat 940 Pixel Breite, und
    die muessen auf 1080 hochgerechnet werden. Bewertet worden war das
    Bild aber, als haette es 2248. Ab jetzt zaehlt, was wirklich da ist.
    """
    try:
        from PIL import Image

        with Image.open(ziel) as offen:
            breite, hoehe = offen.size
    except Exception as exc:  # noqa: BLE001 - dann bleiben die gemeldeten
        log.info("Masse nicht nachgemessen (%s): %s", ziel.name, exc)
        return
    if breite <= 0 or hoehe <= 0:
        return
    if (breite, hoehe) != (bild.breite, bild.hoehe):
        log.info(
            "Gemeldet %sx%s, geladen %sx%s (%s)",
            bild.breite,
            bild.hoehe,
            breite,
            hoehe,
            bild.seite,
        )
    bild.breite, bild.hoehe = breite, hoehe


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
            _uebernimm_echte_masse(bild, ziel)
            return bild
    finally:
        if eigener:
            client.close()

    bild.grund = "; ".join(gruende) or "unbekannt"
    log.info("Bild nicht geladen (%s): %s", bild.seite, bild.grund)
    return None


def schaerfefaktor(wert: float, schwelle: float) -> float:
    """Wie stark ein Bild dadurch verliert, dass es weich ist.

    Eine harte Schwelle war der Fehler. Bei "deep sea creature" wurde
    damit eine echte Tiefseeaufnahme vom Meeresgrund mit 0,56
    ausgeschlossen - und gewonnen hat ein Feuerwerk, das "Deep Sea
    Legend" im Dateinamen hat. Scharf und am Thema vorbei ist wertlos;
    genau darum ging es bei diesem Beitrag nie.

    Die Schwelle war ausserdem an gerechneten Bildern eingestellt.
    Echte Aufnahmen liegen tiefer: Wasser, Kompression, Rauschfilter in
    der Kamera. Ein Wert knapp darunter heisst nicht "unbrauchbar".

    Also ein Abschlag statt eines Ausschlusses, und ein milder: gerade
    so viel, wie der Wert unter der Schwelle liegt. Bei 0,56 gegen 0,62
    bleiben neun Zehntel.

    Milde ist hier keine Bequemlichkeit, sondern Ehrlichkeit ueber das,
    was die Messung kann. Kalibriert ist sie an gerechneten Bildern,
    weil sich echte Aufnahmen hier nicht laden lassen - und auf denen
    liegen die Werte dichter beieinander, als die Kalibrierung glauben
    macht. Eine Zahl, der man nicht ganz trauen kann, darf nicht ueber
    einen Fund entscheiden; sie darf ihn nur ein wenig schieben.

    Die grobe Unschaerfe faengt ohnehin etwas anderes ab: Sie kam davon,
    dass Bilder fuers falsche Format hochgerechnet wurden, und davon,
    dass zu kleine ueberhaupt durchkamen. Beides steckt jetzt in der
    Guete.

    Ein nicht messbarer Wert kostet nichts: Eine Messung, die nichts
    gefunden hat, ist kein Grund abzuwerten.
    """
    if wert <= 0 or schwelle <= 0:
        return 1.0
    return min(1.0, wert / schwelle)


# Was ein Treffer hoechstens erreichen kann - Panoramaform mal voller
# Groesse. Gebraucht, um die Suche abzubrechen, sobald kein Nachfolger
# den bisher Besten mehr einholen kann.
BESTMOEGLICHE_PUNKTE = 1.75


def finde_und_hole(
    suchwort: str,
    ziel: Path,
    *,
    client: httpx.Client | None = None,
    versuche: int = 4,
    beobachter=None,
    groesse: tuple[int, int] = (1080, 1350),
):
    """Suchen, laden und den besten Fund nehmen. None, wenn keiner taugt.

    Es wird nicht der erste brauchbare genommen, sondern der beste - und
    das ist der Unterschied, an dem es zweimal gescheitert ist.

    Beim ersten Mal gewann die Form: "Humpback anglerfish.png", frei,
    gross, gut geschnitten und trotzdem eine wissenschaftliche Zeichnung
    auf Weiss. Beim zweiten Mal gewann die Schaerfe: Eine echte Aufnahme
    vom Meeresgrund flog mit 0,56 raus, und genommen wurde ein Feuerwerk
    namens "Deep Sea Legend following Fireworks" - scharf, gross und zum
    Thema so passend wie nichts.

    Deshalb entscheidet jetzt eine Punktzahl aus dreierlei:

    - dem Platz im Archiv, denn nur die Suchmaschine weiss ueberhaupt
      etwas darueber, ob ein Bild zum Thema gehoert,
    - der Eignung fuers Beitragsformat, gerechnet an den Massen der
      geladenen Datei,
    - der Schaerfe, als Abschlag und nicht als Ausschluss.

    Hart ausgeschlossen wird nur, was gar kein Foto ist. Eine Zeichnung
    auf Weiss traegt keinen Beitrag, egal wie gut sie sonst passt.

    Abgebrochen wird, sobald kein Nachfolger den Besten mehr einholen
    kann - dann werden auch keine Bilder mehr geladen.

    `groesse` ist das Format, in dem der Beitrag erscheint. `beobachter`
    wird fuer jeden Treffer aufgerufen, mit dem Bild, ob es genommen
    wurde und warum nicht. Gedacht fuer die Probe: Wer nachsieht, was
    die Suche tut, will auch sehen, was sie verworfen hat.
    """
    import shutil

    from .fotoprobe import wirkt_wie_foto
    from .schaerfe import SCHARF_GENUG, schaerfewert

    zielverhaeltnis = groesse[0] / groesse[1] if groesse[1] else BEITRAGSVERHAELTNIS
    kandidaten = suche_bilder(suchwort, client=client, zielverhaeltnis=zielverhaeltnis)

    bester: tuple[float, Fundbild, Path] | None = None
    ausgeschieden: list[tuple[Fundbild, str]] = []
    zwischendateien: list[Path] = []

    for platz, bild in enumerate(kandidaten[: max(1, versuche)]):
        if bester is not None and BESTMOEGLICHE_PUNKTE * rangfaktor(platz) <= bester[0]:
            log.info("Suche abgebrochen: Platz %s kann nicht mehr gewinnen", platz + 1)
            break

        entwurf = ziel.with_name(f"{ziel.stem}-v{platz}{ziel.suffix}")
        zwischendateien.append(entwurf)
        geladen = hole_bild(bild, entwurf, client=client)
        if geladen is None:
            ausgeschieden.append((bild, bild.grund or "nicht ladbar"))
            continue

        taugt, grund = wirkt_wie_foto(entwurf)
        if not taugt:
            log.info("Verworfen (%s): %s", bild.seite, grund)
            bild.grund = grund
            ausgeschieden.append((bild, grund))
            continue

        wert = schaerfewert(entwurf, groesse=groesse)
        punkte = (
            guete(bild.breite, bild.hoehe, zielverhaeltnis=zielverhaeltnis)
            * rangfaktor(platz)
            * schaerfefaktor(wert, SCHARF_GENUG)
        )
        log.info(
            "Platz %s: %s (%sx%s, Schaerfe %.2f) - %.2f Punkte",
            platz + 1,
            bild.seite,
            bild.breite,
            bild.hoehe,
            wert,
            punkte,
        )
        if bester is None or punkte > bester[0]:
            if bester is not None:
                ausgeschieden.append(
                    (bester[1], f"ein besserer Treffer kam dazu ({bester[0]:.2f} Punkte)")
                )
            bester = (punkte, geladen, entwurf)
        else:
            ausgeschieden.append((bild, f"weniger geeignet ({punkte:.2f} Punkte)"))

    if beobachter:
        for bild, grund in ausgeschieden:
            beobachter(bild, False, grund)

    if bester is None:
        _raeume_auf(zwischendateien, behalte=None)
        return None

    punkte, gewinner, datei = bester
    try:
        if datei != ziel:
            shutil.copyfile(datei, ziel)
    except OSError as exc:
        log.warning("Fund nicht an seinen Platz gelegt: %s", exc)
        _raeume_auf(zwischendateien, behalte=datei)
        gewinner.pfad = datei
        return gewinner

    _raeume_auf(zwischendateien, behalte=None)
    gewinner.pfad = ziel
    log.info(
        "Genommen: %s (%s, %.2f Punkte)", gewinner.seite, gewinner.lizenz, punkte
    )
    if beobachter:
        beobachter(gewinner, True, "")
    return gewinner


def _raeume_auf(dateien: list[Path], *, behalte: Path | None) -> None:
    """Die Zwischenstaende wegwerfen.

    Ohne das bleibt nach jeder Suche ein halbes Dutzend Dateien im
    Bilderordner liegen, und beim naechsten Mal weiss niemand mehr,
    welche davon im Beitrag steht.
    """
    for datei in dateien:
        if datei == behalte:
            continue
        try:
            datei.unlink(missing_ok=True)
        except OSError as exc:  # noqa: PERF203 - eine Datei weniger ist kein Grund
            log.debug("Zwischenstand nicht geloescht (%s): %s", datei.name, exc)


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
    "schaerfefaktor",
    "massfaktor",
    "nutzmasse",
    "rangfaktor",
]
