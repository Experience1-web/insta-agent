"""Die Abbildungen einer Studie - ueber Europe PMC statt ueber den Verlag.

Im ersten echten Zyklus stand die richtige Studie zur leuchtenden Koralle
in der Liste: frei, unter CC BY, bei der Royal Society. Die Seite
antwortete mit 403. Viele Verlage sperren Programme aus, auch dann, wenn
alles auf der Seite frei ist - sie wollen Menschen im Browser, keine
Abrufe.

Europe PMC ist fuer genau diese Abrufe da. Es ist das oeffentliche Archiv
der Lebens- und Naturwissenschaften, betrieben vom Europaeischen Institut
fuer Bioinformatik, und haelt von offenen Studien den vollen Text mit
allen Abbildungen vor - samt Lizenz in maschinenlesbarer Form. Die
Schnittstelle ist ausdruecklich fuer Programme gebaut und frei nutzbar.

Der Weg hat drei Schritte:

1. Mit der DOI - der festen Kennung jeder Veroeffentlichung - die Studie
   finden. Dabei kommen Lizenz, Autoren und Zeitschrift gleich mit.
2. Ist sie frei (CC BY, CC BY-SA, CC0), den vollen Text holen.
3. Daraus die Abbildungen lesen: Dateiname und Bildunterschrift.

Die Bilder durchlaufen danach dieselbe Pruefung wie alle anderen - Foto
oder Zeichnung, gross genug, scharf genug, und der Blick darauf. In einer
Studie steht oft zuerst eine Karte oder ein Diagramm; die fallen dort
heraus, und die Aufnahme vom Fund bleibt.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from html import unescape

import httpx

from .echtbild import GEDULD, Fundbild, darf_genutzt_werden, kennung

log = logging.getLogger(__name__)

SCHNITTSTELLE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# Unter dieser Adresse liefert Europe PMC die Abbildungen eines Artikels.
BILDADRESSE = "https://europepmc.org/articles/{pmcid}/bin/{datei}"

# So viele Abbildungen werden hoechstens angesehen. Weiter hinten stehen
# in Studien meist Diagramme, Stammbaeume und Tabellen.
HOECHSTENS = 8

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>)\]]+)", re.IGNORECASE)


def finde_doi(*texte: str) -> str:
    """Die erste DOI in diesen Texten - oder nichts.

    DOIs stehen oft in Adressen ("frontiersin.org/articles/10.3389/...",
    "plos.org/...?id=10.1371/...") oder in Quellenangaben ("DOI:
    10.1098/rsos.250890"). Satzzeichen am Ende gehoeren nicht dazu.
    """
    for text in texte:
        if treffer := _DOI.search(str(text or "")):
            return treffer.group(1).rstrip(".,;:")
    return ""


def doi_des_fundes(fund) -> str:
    """Die DOI der Originalstudie - ausdruecklich genannt oder aus den Quellen."""
    if fund is None:
        return ""
    return finde_doi(
        getattr(fund, "doi", "") or "",
        getattr(fund, "bildseite", "") or "",
        *(getattr(fund, "quellen", None) or []),
    )


@dataclass(slots=True)
class Studie:
    """Was Europe PMC ueber eine Studie weiss - soweit es fuer Bilder zaehlt."""

    doi: str
    pmcid: str = ""
    lizenz: str = ""
    urheber: str = ""
    titel: str = ""
    abbildungen: list[tuple[str, str]] = field(default_factory=list)
    """(Bildadresse, Bildunterschrift), in der Reihenfolge der Studie."""
    grund: str = ""


def _lesbare_lizenz(roh: str) -> str:
    """ "cc by" -> "CC BY", "cc0" -> "CC0" - so, wie es in der Pflichtangabe steht."""
    klein = (roh or "").strip().casefold()
    if not klein:
        return ""
    if klein in ("cc0", "cc 0"):
        return "CC0"
    return klein.upper().replace("CC-", "CC ")


def _urheber(eintrag: dict) -> str:
    """Erstautor, "et al." bei mehreren, und die Zeitschrift dahinter."""
    autoren = [a.strip() for a in str(eintrag.get("authorString") or "").split(",") if a.strip()]
    zeitschrift = ""
    info = eintrag.get("journalInfo") or {}
    if isinstance(info, dict):
        zeitschrift = str((info.get("journal") or {}).get("title") or "")
    zeitschrift = zeitschrift or str(eintrag.get("journalTitle") or "")
    if not autoren:
        return zeitschrift
    wer = autoren[0] + (" et al." if len(autoren) > 1 else "")
    return f"{wer} ({zeitschrift})" if zeitschrift else wer


def abbildungen_aus_xml(pmcid: str, xml: str) -> list[tuple[str, str]]:
    """Die Abbildungen aus dem vollen Text: (Adresse, Bildunterschrift).

    Der Text kommt im Format, das alle Fachverlage fuer das Archiv
    liefern. Jede Abbildung steht in einem <fig>, der Dateiname im
    <graphic>, die Unterschrift im <caption>.
    """
    ergebnis: list[tuple[str, str]] = []
    for figur in re.finditer(r"<fig\b.*?</fig>", xml or "", re.DOTALL | re.IGNORECASE):
        stueck = figur.group(0)
        datei = re.search(
            r"""<graphic\b[^>]*?(?:xlink:)?href\s*=\s*["']([^"']+)["']""",
            stueck,
            re.IGNORECASE,
        )
        if not datei:
            continue
        name = datei.group(1).strip()
        if not re.search(r"\.(jpe?g|png|gif|tiff?)$", name, re.IGNORECASE):
            name += ".jpg"
        unterschrift = ""
        if treffer := re.search(r"<caption\b.*?</caption>", stueck, re.DOTALL | re.I):
            unterschrift = re.sub(r"<[^>]+>", " ", treffer.group(0))
            unterschrift = re.sub(r"\s+", " ", unescape(unterschrift)).strip()
        adresse = BILDADRESSE.format(pmcid=pmcid, datei=name)
        if adresse not in (a for a, _ in ergebnis):
            ergebnis.append((adresse, unterschrift[:300]))
    return ergebnis[:HOECHSTENS]


def finde_studie(doi: str, *, client: httpx.Client | None = None) -> Studie:
    """Sucht die Studie zu dieser DOI und holt ihre Abbildungen - wenn sie frei ist."""
    studie = Studie(doi=doi)
    if not doi:
        studie.grund = "keine DOI"
        return studie

    eigener = client is None
    client = client or httpx.Client(timeout=GEDULD, follow_redirects=True)
    kopf = {"User-Agent": kennung(), "Accept": "application/json"}
    try:
        try:
            antwort = client.get(
                f"{SCHNITTSTELLE}/search",
                params={
                    "query": f'DOI:"{doi}"',
                    "format": "json",
                    "resultType": "core",
                    "pageSize": "1",
                },
                headers=kopf,
            )
        except Exception as exc:  # noqa: BLE001 - dann eben nicht
            studie.grund = f"Europe PMC nicht erreichbar ({type(exc).__name__})"
            return studie
        if antwort.status_code >= 400:
            studie.grund = f"Europe PMC antwortete mit HTTP {antwort.status_code}"
            return studie

        try:
            treffer = (antwort.json().get("resultList") or {}).get("result") or []
        except ValueError:
            studie.grund = "Europe PMC lieferte keine lesbare Antwort"
            return studie
        if not treffer:
            studie.grund = "Studie bei Europe PMC nicht gefunden"
            return studie

        eintrag = treffer[0]
        studie.pmcid = str(eintrag.get("pmcid") or "")
        studie.lizenz = _lesbare_lizenz(str(eintrag.get("license") or ""))
        studie.urheber = _urheber(eintrag)
        studie.titel = str(eintrag.get("title") or "")

        if not studie.pmcid:
            studie.grund = "Studie ohne vollen Text im Archiv"
            return studie
        if not darf_genutzt_werden(studie.lizenz):
            studie.grund = (
                f"Lizenz {studie.lizenz or 'unbekannt'} erlaubt keine "
                "gewerbliche Nutzung mit Bearbeitung"
            )
            return studie

        try:
            text = client.get(
                f"{SCHNITTSTELLE}/{studie.pmcid}/fullTextXML",
                headers={"User-Agent": kennung(), "Accept": "application/xml"},
            )
        except Exception as exc:  # noqa: BLE001
            studie.grund = f"Volltext nicht erreichbar ({type(exc).__name__})"
            return studie
        if text.status_code >= 400:
            studie.grund = f"Volltext antwortete mit HTTP {text.status_code}"
            return studie

        studie.abbildungen = abbildungen_aus_xml(studie.pmcid, text.text)
        if not studie.abbildungen:
            studie.grund = "keine Abbildungen im Volltext"
    finally:
        if eigener:
            client.close()
    return studie


def kandidaten_der_studie(studie: Studie) -> list[Fundbild]:
    """Die Abbildungen als Kandidaten fuer dieselbe Pruefung wie alle anderen."""
    seite = f"https://europepmc.org/article/PMC/{studie.pmcid}"
    return [
        Fundbild(
            url=adresse,
            pfad=None,
            lizenz=studie.lizenz,
            urheber=studie.urheber,
            seite=seite,
            breite=0,
            hoehe=0,
            verweis=seite,
            quelle="Europe PMC",
        )
        for adresse, _unterschrift in studie.abbildungen
    ]


__all__ = [
    "Studie",
    "abbildungen_aus_xml",
    "doi_des_fundes",
    "finde_doi",
    "finde_studie",
    "kandidaten_der_studie",
]
