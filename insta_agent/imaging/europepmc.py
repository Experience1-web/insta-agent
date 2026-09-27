"""Die Abbildungen einer Studie - ueber die offenen Archive statt ueber den Verlag.

Im ersten echten Zyklus stand die richtige Studie zur leuchtenden Koralle
in der Liste: frei, unter CC BY, bei der Royal Society. Die Seite
antwortete mit 403. Viele Verlage sperren Programme aus, auch wenn alles
auf der Seite frei ist.

Fuer offene Studien gibt es zwei oeffentliche Archive, die fuer Programme
gebaut sind, und beide werden hier gebraucht:

1. Europe PMC findet die Studie. Mit der DOI - der festen Kennung jeder
   Veroeffentlichung - kommen die Archivnummer, die Lizenz, die Autoren
   und die Zeitschrift.
2. Das Datenarchiv von PubMed Central haelt jede offene Studie als Paket
   bereit: eine Beschreibung mit Lizenz, das PDF und die Abbildungen als
   Bilddateien. Es liegt oeffentlich in der Cloud, gedacht fuer genau
   diese Abrufe.

Der naheliegende dritte Weg - die Bildadressen auf europepmc.org - ist
fuer Programme gesperrt. Das hat erst ein echter Abruf gezeigt: 403 bei
allen fuenf Abbildungen der Korallenstudie.

Die Abbildungen im Datenarchiv sind allerdings Vorschaufassungen, oft
kaum 750 Pixel breit und als Tafel mehrerer Einzelbilder. Die Aufnahmen
in voller Groesse stecken im PDF; das liest `pdfbilder`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from html import unescape

import httpx

from .echtbild import GEDULD, darf_genutzt_werden, kennung

log = logging.getLogger(__name__)

SCHNITTSTELLE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
DATENARCHIV = "https://pmc-oa-opendata.s3.amazonaws.com"

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
    """Was die Archive ueber eine Studie wissen - soweit es fuer Bilder zaehlt."""

    doi: str
    pmcid: str = ""
    lizenz: str = ""
    urheber: str = ""
    titel: str = ""
    pdf: str = ""
    """Adresse des PDF im Datenarchiv - dort stecken die grossen Fassungen."""
    pdf_groesse: int = 0
    abbildungen: list[str] = field(default_factory=list)
    """Die Vorschaufassungen der Abbildungen, in der Reihenfolge der Studie."""
    grund: str = ""

    @property
    def seite(self) -> str:
        """Wo ein Mensch die Studie nachlesen kann."""
        return f"https://europepmc.org/article/PMC/{self.pmcid}" if self.pmcid else ""


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
    wer = autoren[0].rstrip(".") + (" et al." if len(autoren) > 1 else "")
    return f"{wer} ({zeitschrift})" if zeitschrift else wer


def _aus_s3(adresse: str) -> str:
    """ "s3://pmc-oa-opendata/PMC1.1/x.jpg?md5=..." -> oeffentliche Adresse."""
    ohne = adresse.split("?", 1)[0]
    if ohne.startswith("s3://pmc-oa-opendata/"):
        return f"{DATENARCHIV}/{ohne[len('s3://pmc-oa-opendata/'):]}"
    return ohne if ohne.startswith("http") else ""


def _neueste_fassung(pmcid: str, client: httpx.Client) -> tuple[str, dict[str, int]]:
    """Das Verzeichnis der neuesten Fassung im Datenarchiv und seine Dateien.

    Studien werden korrigiert; jede Fassung liegt in einem eigenen
    Verzeichnis ("PMC12585878.1/", ".2/"). Genommen wird die hoechste.
    """
    antwort = client.get(
        f"{DATENARCHIV}/",
        params={"list-type": "2", "prefix": f"{pmcid}."},
        headers={"User-Agent": kennung()},
    )
    if antwort.status_code >= 400:
        return "", {}
    dateien = {
        schluessel: int(groesse)
        for schluessel, groesse in re.findall(
            r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", antwort.text, re.DOTALL
        )
    }
    fassungen = {
        schluessel.split("/", 1)[0]
        for schluessel in dateien
        if re.match(rf"{re.escape(pmcid)}\.\d+/", schluessel)
    }
    if not fassungen:
        return "", {}
    neueste = max(fassungen, key=lambda f: int(f.rsplit(".", 1)[1]))
    return neueste, {k: v for k, v in dateien.items() if k.startswith(neueste + "/")}


def finde_studie(doi: str, *, client: httpx.Client | None = None) -> Studie:
    """Sucht die Studie zu dieser DOI und stellt fest, welche Bilder es gibt."""
    studie = Studie(doi=doi)
    if not doi:
        studie.grund = "keine DOI"
        return studie

    eigener = client is None
    client = client or httpx.Client(timeout=GEDULD, follow_redirects=True)
    try:
        # 1. Europe PMC: Archivnummer, Lizenz, Autoren
        try:
            antwort = client.get(
                f"{SCHNITTSTELLE}/search",
                params={
                    "query": f'DOI:"{doi}"',
                    "format": "json",
                    "resultType": "core",
                    "pageSize": "1",
                },
                headers={"User-Agent": kennung(), "Accept": "application/json"},
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
        studie.titel = re.sub(r"<[^>]+>", "", unescape(str(eintrag.get("title") or "")))

        if not studie.pmcid:
            studie.grund = "Studie ohne vollen Text im Archiv"
            return studie

        # 2. Datenarchiv: Lizenz, PDF, Abbildungen
        try:
            verzeichnis, dateien = _neueste_fassung(studie.pmcid, client)
        except Exception as exc:  # noqa: BLE001
            studie.grund = f"Datenarchiv nicht erreichbar ({type(exc).__name__})"
            return studie
        if not verzeichnis:
            studie.grund = "Studie nicht im offenen Datenarchiv"
            return studie

        try:
            beschreibung = client.get(
                f"{DATENARCHIV}/{verzeichnis}/{verzeichnis}.json",
                headers={"User-Agent": kennung()},
            ).json()
        except Exception as exc:  # noqa: BLE001
            studie.grund = f"Beschreibung im Datenarchiv nicht lesbar ({type(exc).__name__})"
            return studie

        # Die Lizenz aus dem Datenarchiv gilt vor der aus der Suche - sie
        # steht an der Datei, die wir tatsaechlich nehmen.
        if lizenz := _lesbare_lizenz(str(beschreibung.get("license_code") or "")):
            studie.lizenz = lizenz
        if not darf_genutzt_werden(studie.lizenz):
            studie.grund = (
                f"Lizenz {studie.lizenz or 'unbekannt'} erlaubt keine "
                "gewerbliche Nutzung mit Bearbeitung"
            )
            return studie

        studie.abbildungen = [
            adresse
            for roh in beschreibung.get("media_urls") or []
            if (adresse := _aus_s3(str(roh)))
            and re.search(r"\.(jpe?g|png|gif|tiff?)$", adresse, re.IGNORECASE)
        ]
        if pdf := _aus_s3(str(beschreibung.get("pdf_url") or "")):
            studie.pdf = pdf
            schluessel = pdf[len(DATENARCHIV) + 1 :]
            studie.pdf_groesse = dateien.get(schluessel, 0)

        if not studie.abbildungen and not studie.pdf:
            studie.grund = "keine Abbildungen im Archiv"
    finally:
        if eigener:
            client.close()
    return studie


__all__ = [
    "DATENARCHIV",
    "Studie",
    "doi_des_fundes",
    "finde_doi",
    "finde_studie",
]
