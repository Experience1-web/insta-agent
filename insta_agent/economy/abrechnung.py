"""Die echte Abrechnung von Anthropic lesen, statt sie zu schätzen.

Die Kasse rechnet sonst mit, was ein Aufruf kosten *sollte*: Tokenzahl mal
Preisliste. Das geht schief, sobald sich Preise ändern oder jemand den
Schlüssel noch woanders benutzt - und die Grenzen für Sparbetrieb und Stopp
hängen daran.

Ein Guthaben gibt die API nicht heraus; einen solchen Endpunkt gibt es
nicht. Was sie herausgibt, sind die tatsächlich abgerechneten Kosten pro
Tag. Daraus wird das Guthaben gerechnet: ein einmal eingetragener Stand,
minus alles, was seitdem wirklich angefallen ist.

Der Schlüssel dafür ist ein Admin-Schlüssel, und der kann mehr als lesen -
er darf auch API-Schlüssel anlegen und widerrufen. Er wird deshalb
ausschließlich hier verwendet, in einem einzigen lesenden Aufruf. In einen
Prompt gerät er nie: Das Modell sieht die fertige Zahl, nicht den Weg
dorthin. Ein Agent, der fremde Webseiten liest, bekommt keine Schlüssel in
die Hand.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

ADRESSE = "https://api.anthropic.com/v1/organizations/cost_report"
VERSION = "2023-06-01"

# Die Abrechnung kennt nur ganze Tage. Mehr als 31 gibt sie pro Seite nicht
# heraus, deshalb wird geblättert.
TAGE_PRO_SEITE = 31

# Beträge kommen als Dezimalzeichenkette in der kleinsten Währungseinheit:
# "123.45" USD sind 1,2345 Dollar.
CENT_PRO_DOLLAR = 100


class Abrechnungsfehler(RuntimeError):
    """Die Abrechnung liess sich nicht abrufen."""


def tagesbeginn(zeitpunkt: datetime) -> datetime:
    """Der Anfang des Tages in UTC, auf den die Abrechnung ihre Töpfe legt."""
    return zeitpunkt.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


class Abrechnung:
    def __init__(self, admin_key: str, *, timeout: float = 30.0) -> None:
        self.admin_key = admin_key
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def kosten_seit(self, beginn: datetime) -> float:
        """Summe aller abgerechneten Kosten ab diesem Tag, in USD.

        Gerechnet wird ab dem Tagesbeginn: Feiner als einen Tag löst die
        Abrechnung nicht auf.
        """
        von = tagesbeginn(beginn)
        gesamt = 0.0
        seite: str | None = None

        while True:
            daten = self._hole(von, seite)
            for topf in daten.get("data") or []:
                for posten in topf.get("results") or []:
                    gesamt += _in_dollar(posten)
            if not daten.get("has_more"):
                break
            seite = daten.get("next_page")
            if not seite:
                break

        return round(gesamt, 6)

    def _hole(self, von: datetime, seite: str | None) -> dict:
        params: dict[str, str | int] = {
            "starting_at": von.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bucket_width": "1d",
            "limit": TAGE_PRO_SEITE,
        }
        if seite:
            params["page"] = seite

        try:
            antwort = self.client.get(
                ADRESSE,
                params=params,
                headers={"x-api-key": self.admin_key, "anthropic-version": VERSION},
            )
        except httpx.HTTPError as exc:
            raise Abrechnungsfehler(f"Die Abrechnung war nicht erreichbar: {exc}") from exc

        if antwort.status_code >= 400:
            raise Abrechnungsfehler(_lesbar(antwort))

        try:
            return antwort.json()
        except ValueError as exc:
            raise Abrechnungsfehler("Die Abrechnung antwortete nicht in JSON.") from exc


def _in_dollar(posten: dict) -> float:
    """Ein Posten der Abrechnung als Dollarbetrag.

    Eine unverständliche Zeile darf nicht die ganze Summe kippen - sie
    wird übergangen und vermerkt, damit die anderen weiter zählen.
    """
    waehrung = posten.get("currency", "USD")
    if waehrung != "USD":
        log.warning("Posten in fremder Währung übergangen: %s", waehrung)
        return 0.0
    try:
        return float(posten.get("amount", 0)) / CENT_PRO_DOLLAR
    except (TypeError, ValueError):
        log.warning("Unlesbarer Betrag in der Abrechnung: %r", posten.get("amount"))
        return 0.0


def _lesbar(antwort: httpx.Response) -> str:
    if antwort.status_code in (401, 403):
        # Welcher Schlüssel das war, weiß diese Stelle nicht - die Meldung
        # muss deshalb für beide Fälle stimmen.
        return (
            "Dieser Schlüssel darf die Abrechnung nicht lesen. Dafür braucht es "
            "einen Admin-Schlüssel: platform.claude.com/settings/admin-keys"
        )
    if antwort.status_code == 404:
        return (
            "Diese Schnittstelle gibt es für dieses Konto nicht. Der Stand lässt "
            "sich von Hand eintragen mit `insta-agent kasse <Betrag>`."
        )
    if antwort.status_code == 429:
        return "Zu viele Abfragen der Abrechnung. Beim nächsten Zyklus wieder."
    return f"Die Abrechnung antwortete mit {antwort.status_code}."


def baue_abrechnung(admin_key: str | None) -> Abrechnung | None:
    """None heisst: kein Admin-Schluessel - dann bleibt es beim Schaetzen."""
    return Abrechnung(admin_key) if admin_key else None
