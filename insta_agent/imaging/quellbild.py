"""Die Aufnahmen vom Fund selbst - aus der Studie, von der Behoerde.

Die Archivsuche findet Bilder, die zum Thema passen. Das ist gut, um ein
Karussell zu fuellen, aber es ist nicht das Ziel. Wer liest, dass in
Schottland ein Goldschatz gefunden wurde, will diesen Schatz sehen und
diesen Fundort - nicht irgendeinen Goldschatz.

Solche Bilder gibt es fast immer, und sie stammen fast immer von
derselben Stelle: aus der Veroeffentlichung, in der der Fund beschrieben
wird, oder von der Einrichtung, die ihn gemacht hat. Die Zeitungen, die
darueber berichten, zeigen dieselben Aufnahmen - aber mit einem
Agenturvermerk, und die Rechte daran sind nicht frei. Ein Bild aus einem
Nachrichtenartikel zu nehmen, kostet im Wiederholungsfall das Konto.

Die Quelle selbst ist oft frei. Offene Fachzeitschriften veroeffentlichen
unter CC BY - Abbildungen eingeschlossen -, und was eine US-Bundesbehoerde
wie die NASA aufnimmt, ist von Gesetzes wegen gemeinfrei. Dort holt
dieses Modul die Bilder ab.

Genommen wird nur, was sich mechanisch belegen laesst:

- Bei einer Behoerde reicht die Adresse. Die Gemeinfreiheit folgt aus
  dem Gesetz, nicht aus einem Vermerk auf der Seite.
- Bei einer Zeitschrift muss der Lizenzvermerk auf der Seite stehen,
  als Verweis auf die Creative-Commons-Lizenz. Steht dort zugleich ein
  NC oder ND, wird nichts genommen - im Zweifel lieber ein Archivbild.
- Alle anderen Seiten werden gar nicht erst aufgerufen. Ein CC-Vermerk
  auf einer Nachrichtenseite gilt oft nur fuer den Text, die Bilder sind
  von einer Agentur - genau die Falle, die hier vermieden werden soll.

Ob das, was eine Seite zeigt, zum Fund gehoert, entscheidet danach
dieselbe Pruefung wie bei Archivbildern: Foto oder Zeichnung, gross
genug, scharf genug, und - wenn eingeschaltet - ein Blick darauf.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .echtbild import GEDULD, Fundbild, darf_genutzt_werden, kennung, waehle_bestes

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Quelle:
    """Eine Stelle, von der Bilder genommen werden duerfen - und warum."""

    endung: str
    """Die Adresse endet hierauf, zum Beispiel "plos.org"."""

    name: str
    """So steht sie in der Pflichtangabe."""

    gemeinfrei: bool
    """True: Behoerde, gemeinfrei von Gesetzes wegen, kein Vermerk noetig.
    False: Zeitschrift, der Lizenzvermerk muss auf der Seite stehen."""

    zeitschrift: bool = False
    """True: Dann kommt nur eine Artikelseite infrage, keine Startseite."""


FREIE_QUELLEN: tuple[Quelle, ...] = (
    # US-Bundesbehoerden. Was ihre Angestellten im Dienst aufnehmen, ist
    # nach US-Recht gemeinfrei. Einzelne Bilder Dritter koennen darunter
    # sein - das ist das Restrisiko, und es ist klein.
    Quelle("nasa.gov", "NASA", gemeinfrei=True),
    Quelle("noaa.gov", "NOAA", gemeinfrei=True),
    Quelle("usgs.gov", "USGS", gemeinfrei=True),
    Quelle("nps.gov", "National Park Service", gemeinfrei=True),
    Quelle("fws.gov", "U.S. Fish and Wildlife Service", gemeinfrei=True),
    # Die ESA veroeffentlicht viel unter CC BY-SA 3.0 IGO, aber nicht
    # alles - also mit Vermerk.
    Quelle("esa.int", "ESA", gemeinfrei=False),
    # Offene Fachzeitschriften. Dort werden neue Arten beschrieben,
    # Grabungen dokumentiert, Funde vorgestellt - mit den Aufnahmen, um
    # die es geht.
    Quelle("plos.org", "PLOS", gemeinfrei=False, zeitschrift=True),
    Quelle("pensoft.net", "Pensoft", gemeinfrei=False, zeitschrift=True),
    Quelle("frontiersin.org", "Frontiers", gemeinfrei=False, zeitschrift=True),
    Quelle("mdpi.com", "MDPI", gemeinfrei=False, zeitschrift=True),
    Quelle("elifesciences.org", "eLife", gemeinfrei=False, zeitschrift=True),
    Quelle("peerj.com", "PeerJ", gemeinfrei=False, zeitschrift=True),
    Quelle("biomedcentral.com", "BMC", gemeinfrei=False, zeitschrift=True),
    Quelle("springeropen.com", "SpringerOpen", gemeinfrei=False, zeitschrift=True),
    Quelle("royalsocietypublishing.org", "Royal Society", gemeinfrei=False, zeitschrift=True),
    # Bei Nature und Science ist nur ein Teil offen - Scientific Reports,
    # Nature Communications, Science Advances. Der Vermerk entscheidet.
    Quelle("nature.com", "Nature", gemeinfrei=False, zeitschrift=True),
    Quelle("science.org", "Science", gemeinfrei=False, zeitschrift=True),
)

# Groesser wird keine Seite geladen. Eine Fachartikelseite hat selten
# mehr als ein, zwei Megabyte; was darueber liegt, ist kein Artikel.
SEITENGRENZE = 4_000_000

# So viele Bilder einer Seite werden hoechstens angesehen. Das
# Aufmacherbild und die ersten Abbildungen - weiter hinten stehen
# meist Diagramme und Tabellen.
HOECHSTENS = 8

# Was in einer Bildadresse auf Beiwerk hindeutet statt auf eine Aufnahme.
BEIWERK = (
    "logo",
    "icon",
    "sprite",
    "avatar",
    "banner",
    "badge",
    "button",
    "orcid",
    "crossmark",
    "altmetric",
    "placeholder",
    "spinner",
    "social",
    "share",
    "flag",
    "/ads/",
    ".svg",
    ".gif",
)


# Woran eine Uebersichtsseite zu erkennen ist - auch wenn "article" drin steht.
UEBERSICHT = (
    "browse",
    "search",
    "issue",
    "archive",
    "latest",
    "about",
    "subscribe",
    "authors",
    "toc",
    "collections",
)


def ist_artikelseite(adresse: str) -> bool:
    """Ob eine Adresse auf einen einzelnen Artikel zeigt und nicht auf eine Uebersicht.

    Aus dem ersten echten Zyklus: Die Stoffsuche nannte
    "zookeys.pensoft.net/" und "zookeys.pensoft.net/browse_articles".
    Auf der Startseite steht die Lizenz im Fuss, also galt sie als frei -
    und ihr Titelbild, eine Zeitschrift mit einem gruenen Frosch, stand
    danach in einem Beitrag ueber eine Koralle.

    Eine Artikelseite erkennt man an der Adresse: "/article/12345",
    "/articles/10.3389/...", "/doi/10.1126/...", oder an einer langen
    Nummer wie bei MDPI. Eine Uebersicht an ihren Woertern, selbst wenn
    "article" darin vorkommt wie in "browse_articles".
    """
    teile = urlparse(adresse or "")
    pfad = (teile.path or "").casefold()
    abfrage = (teile.query or "").casefold()
    if not pfad.strip("/"):
        return False
    if any(wort in pfad for wort in UEBERSICHT):
        return False
    # Eine Suche ist keine Seite ueber einen Fund, auch unter /articles/.
    if re.search(r"(^|&)(q|query|search|keywords?)=", abfrage):
        return False
    return bool(
        # /article/12345, /articles/10.3389/... - es folgt etwas
        re.search(r"/articles?/[^/]+", pfad)
        # PLOS: /plosone/article?id=10.1371/...
        or (re.search(r"/articles?/?$", pfad) and "id=" in abfrage)
        or "/doi/" in pfad
        or re.search(r"\d{4,}", pfad)
    )


def erkenne_quelle(adresse: str) -> Quelle | None:
    """Welche freie Quelle hinter dieser Adresse steht - oder keine.

    Verglichen wird an der Punktgrenze. "fakenasa.gov" ist nicht die
    NASA, "images.nasa.gov" schon.
    """
    rechner = (urlparse(adresse or "").hostname or "").casefold()
    if not rechner:
        return None
    for quelle in FREIE_QUELLEN:
        if rechner == quelle.endung or rechner.endswith("." + quelle.endung):
            return quelle
    return None


_CC_VERWEIS = re.compile(
    r"creativecommons\.org/(licenses|publicdomain)/([a-z-]+)/(\d\.\d)(/igo)?",
    re.IGNORECASE,
)


def lizenz_der_seite(html: str) -> str | None:
    """Die Creative-Commons-Lizenz, die auf der Seite verlinkt ist.

    None heisst: keine, oder eine, die wir nicht nehmen duerfen. Stehen
    mehrere da und ist eine davon NC oder ND, gilt die ganze Seite als
    gesperrt - welche Lizenz fuer welches Bild gilt, laesst sich dann
    nicht mehr auseinanderhalten.
    """
    gefunden: list[str] = []
    for treffer in _CC_VERWEIS.finditer(html or ""):
        art, kuerzel, fassung, igo = (g or "" for g in treffer.groups())
        kuerzel = kuerzel.casefold()
        if art.casefold() == "publicdomain":
            lesbar = "CC0 " + fassung if kuerzel == "zero" else "Public domain"
        else:
            lesbar = f"CC {kuerzel.upper()} {fassung}" + (" IGO" if igo else "")
        if lesbar not in gefunden:
            gefunden.append(lesbar)

    if not gefunden:
        return None
    if not all(darf_genutzt_werden(lizenz) for lizenz in gefunden):
        return None
    return gefunden[0]


def _meta(html: str, *namen: str) -> list[str]:
    """Die Inhalte aller Meta-Angaben mit einem dieser Namen, in Reihenfolge."""
    werte: list[str] = []
    for tag in re.finditer(r"<meta\b[^>]*>", html or "", re.IGNORECASE):
        roh = tag.group(0)
        name = re.search(r"""(?:name|property)\s*=\s*["']([^"']+)["']""", roh, re.I)
        inhalt = re.search(r"""content\s*=\s*["']([^"']*)["']""", roh, re.I)
        if name and inhalt and name.group(1).casefold() in namen:
            wert = unescape(inhalt.group(1)).strip()
            if wert:
                werte.append(wert)
    return werte


def urheber_der_seite(html: str, quelle: Quelle) -> str:
    """Wer genannt werden muss - die Autoren der Studie, sonst die Quelle.

    Fachzeitschriften tragen ihre Autoren in einheitlichen Meta-Angaben,
    die Suchmaschinen fuer Wissenschaft lesen. Genannt wird der erste,
    bei mehreren mit "et al." - so steht es auch in jeder Fachzitierung.
    """
    autoren = _meta(html, "citation_author", "dc.creator")
    zeitschrift = next(iter(_meta(html, "citation_journal_title")), "")
    if not autoren:
        return zeitschrift or quelle.name
    wer = autoren[0] + (" et al." if len(autoren) > 1 else "")
    return f"{wer} ({zeitschrift})" if zeitschrift else wer


def bildkandidaten(seite: str, html: str) -> list[str]:
    """Die Bilder einer Seite, die als Aufnahme infrage kommen, in Reihenfolge.

    Zuerst das Aufmacherbild, das die Seite selbst fuer Vorschauen
    angibt - bei Studien meist die erste Abbildung, bei Behoerden das
    Hauptfoto. Danach Verweise auf grosse Fassungen, dann die Bilder im
    Text, jeweils die groesste Fassung, die angeboten wird.

    Beiwerk faellt vorher raus: Logos, Symbole, Knoepfe. Alles andere
    entscheidet die Pruefung nach dem Laden - ob es ein Foto ist, ob es
    gross genug ist, ob es die Sache zeigt.
    """
    roh: list[str] = []
    roh += _meta(html, "og:image", "og:image:url", "twitter:image", "twitter:image:src")

    # Verweise auf grosse Fassungen: Dateien, und die Figurenadressen,
    # die manche Zeitschriften ohne Dateiendung ausliefern.
    for treffer in re.finditer(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["']""", html or "", re.I):
        ziel = unescape(treffer.group(1))
        klein = ziel.casefold()
        if re.search(r"\.(jpe?g|png|tiff?|webp)(\?|$)", klein) or (
            "figure" in klein and ("size=large" in klein or "original" in klein)
        ):
            roh.append(ziel)

    # Bilder im Text - aus srcset die groesste Fassung.
    for tag in re.finditer(r"<img\b[^>]*>", html or "", re.I):
        stueck = tag.group(0)
        satz = re.search(r"""srcset\s*=\s*["']([^"']+)["']""", stueck, re.I)
        if satz:
            fassungen = []
            for teil in satz.group(1).split(","):
                bits = teil.strip().split()
                if not bits:
                    continue
                breite = 0
                if len(bits) > 1 and bits[1].endswith("w") and bits[1][:-1].isdigit():
                    breite = int(bits[1][:-1])
                fassungen.append((breite, bits[0]))
            if fassungen:
                roh.append(unescape(max(fassungen)[1]))
                continue
        for attribut in ("data-src", "data-original", "src"):
            quelle = re.search(
                rf"""\b{attribut}\s*=\s*["']([^"']+)["']""", stueck, re.I
            )
            if quelle:
                roh.append(unescape(quelle.group(1)))
                break

    kandidaten: list[str] = []
    for adresse in roh:
        voll = urljoin(seite, adresse.strip())
        if not voll.startswith("http"):
            continue
        if any(beiwerk in voll.casefold() for beiwerk in BEIWERK):
            continue
        if voll not in kandidaten:
            kandidaten.append(voll)
    return kandidaten[:HOECHSTENS]


@dataclass(slots=True)
class Seitenbefund:
    """Was eine Quellseite hergibt - fuer die Probe und fuer das Protokoll."""

    seite: str
    quelle: Quelle | None = None
    lizenz: str = ""
    urheber: str = ""
    kandidaten: list[str] | None = None
    grund: str = ""


def pruefe_seite(
    seite: str, *, client: httpx.Client | None = None
) -> Seitenbefund:
    """Laedt eine Quellseite und stellt fest, ob und welche Bilder sie hergibt.

    Eine Seite, die keine freie Quelle ist, wird nicht einmal aufgerufen.
    """
    befund = Seitenbefund(seite=seite)
    befund.quelle = erkenne_quelle(seite)
    if befund.quelle is None:
        befund.grund = "keine freie Quelle - Bilder dort sind meist geschützt"
        return befund

    eigener = client is None
    client = client or httpx.Client(timeout=GEDULD, follow_redirects=True)
    try:
        try:
            antwort = client.get(
                seite,
                headers={
                    "User-Agent": kennung(),
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                },
            )
        except Exception as exc:  # noqa: BLE001 - dann eben keine Quellbilder
            befund.grund = f"Seite nicht erreichbar ({type(exc).__name__})"
            return befund
    finally:
        if eigener:
            client.close()

    if antwort.status_code >= 400:
        befund.grund = f"Seite antwortete mit HTTP {antwort.status_code}"
        return befund
    if len(antwort.content) > SEITENGRENZE:
        befund.grund = "Seite zu groß, das ist kein Artikel"
        return befund

    html = antwort.text
    if befund.quelle.gemeinfrei:
        befund.lizenz = "Public domain"
    else:
        lizenz = lizenz_der_seite(html)
        if lizenz is None:
            befund.grund = (
                "kein freier Lizenzvermerk auf der Seite (oder NC/ND dabei)"
            )
            return befund
        befund.lizenz = lizenz

    befund.urheber = urheber_der_seite(html, befund.quelle)
    befund.kandidaten = bildkandidaten(str(antwort.url), html)
    if not befund.kandidaten:
        befund.grund = "keine Bilder auf der Seite gefunden"
    return befund


def aus_der_quelle(
    seiten: list[str],
    ziel: Path,
    *,
    client: httpx.Client | None = None,
    blick=None,
    groesse: tuple[int, int] = (1080, 1350),
    beobachter=None,
    weitere: list[Fundbild] | None = None,
    befunde: list[Seitenbefund] | None = None,
) -> Fundbild | None:
    """Das beste Bild vom Fund selbst, aus der ersten Quelle, die eines hergibt.

    `seiten` sind die Adressen, die die Stoffsuche genannt hat - Studie,
    Behoerde, Quellen. Probiert wird der Reihe nach; die erste Seite, von
    der ein Bild die Pruefung besteht, gewinnt. `weitere` sammelt die
    uebrigen brauchbaren Bilder derselben Seite fuers Karussell, und
    `befunde` haelt fest, was jede Seite ergeben hat.
    """
    gesehen: set[str] = set()
    for seite in seiten:
        seite = (seite or "").strip()
        if not seite.startswith("http") or seite in gesehen:
            continue
        gesehen.add(seite)

        befund = pruefe_seite(seite, client=client)
        if befunde is not None:
            befunde.append(befund)
        if not befund.kandidaten:
            log.info("Quellseite ohne Bild (%s): %s", seite, befund.grund)
            continue

        kandidaten = [
            Fundbild(
                url=adresse,
                pfad=None,
                lizenz=befund.lizenz,
                urheber=befund.urheber,
                seite=seite,
                breite=0,
                hoehe=0,
                verweis=seite,
                quelle=befund.quelle.name if befund.quelle else "",
            )
            for adresse in befund.kandidaten
        ]
        gefunden = waehle_bestes(
            kandidaten,
            ziel,
            client=client,
            versuche=len(kandidaten),
            beobachter=beobachter,
            groesse=groesse,
            blick=blick,
            weitere=weitere,
        )
        if gefunden is not None:
            return gefunden
        befund.grund = "kein Bild der Seite hat die Prüfung bestanden"
    return None


def aus_der_studie(
    doi: str,
    ziel: Path,
    *,
    client: httpx.Client | None = None,
    blick=None,
    groesse: tuple[int, int] = (1080, 1350),
    beobachter=None,
    weitere: list[Fundbild] | None = None,
    befunde: list[Seitenbefund] | None = None,
) -> Fundbild | None:
    """Das beste Bild aus den Abbildungen einer Studie, ueber Europe PMC.

    Der Weg an Verlagen vorbei, die Programme aussperren. Siehe
    `europepmc` - dort steht auch, warum das kein Umweg ist, sondern der
    vorgesehene Zugang.
    """
    from .europepmc import finde_studie, kandidaten_der_studie

    studie = finde_studie(doi, client=client)
    befund = Seitenbefund(
        seite=f"Europe PMC (DOI {doi})",
        lizenz=studie.lizenz,
        urheber=studie.urheber,
        kandidaten=[adresse for adresse, _ in studie.abbildungen] or None,
        grund=studie.grund,
    )
    if befunde is not None:
        befunde.append(befund)

    kandidaten = kandidaten_der_studie(studie)
    if not kandidaten:
        log.info("Keine Abbildungen ueber Europe PMC (%s): %s", doi, studie.grund)
        return None

    gefunden = waehle_bestes(
        kandidaten,
        ziel,
        client=client,
        versuche=len(kandidaten),
        beobachter=beobachter,
        groesse=groesse,
        blick=blick,
        weitere=weitere,
    )
    if gefunden is None:
        befund.grund = "keine Abbildung der Studie hat die Prüfung bestanden"
    return gefunden


def quellseiten(fund) -> list[str]:
    """Die Adressen eines Fundes, an denen Bilder vom Fund selbst stehen koennten.

    Zuerst, was die Stoffsuche ausdruecklich als Bildquelle genannt hat,
    dann die Quellen des Fundes - dort steht die Studie oft ohnehin. Nur
    freie Quellen; alles andere wird nicht einmal aufgerufen.
    """
    if fund is None:
        return []
    roh = [
        getattr(fund, "bildseite", "") or "",
        getattr(fund, "echtes_bild", "") or "",
        *(getattr(fund, "quellen", None) or []),
    ]
    seiten: list[str] = []
    for eintrag in roh:
        for adresse in re.findall(r"https?://[^\s<>\"')\]]+", str(eintrag)):
            adresse = adresse.rstrip(".,;")
            quelle = erkenne_quelle(adresse)
            if quelle is None or adresse in seiten:
                continue
            # Eine Behoerdenseite braucht wenigstens einen Pfad, eine
            # Zeitschrift einen Artikel - Startseiten zeigen Werbung fuer
            # sich selbst, nicht den Fund.
            if quelle.zeitschrift and not ist_artikelseite(adresse):
                continue
            if not (urlparse(adresse).path or "").strip("/"):
                continue
            seiten.append(adresse)
    return seiten[:3]


__all__ = [
    "FREIE_QUELLEN",
    "Quelle",
    "Seitenbefund",
    "aus_der_quelle",
    "aus_der_studie",
    "bildkandidaten",
    "erkenne_quelle",
    "ist_artikelseite",
    "lizenz_der_seite",
    "pruefe_seite",
    "quellseiten",
    "urheber_der_seite",
]
