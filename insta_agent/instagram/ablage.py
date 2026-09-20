"""Einen öffentlichen Platz für die fertigen Bilder.

Instagram nimmt keine Datei entgegen. Es bekommt eine Adresse und holt
sich das Bild selbst. Der Rechner des Betreibers ist von außen nicht
erreichbar, also muss das Bild kurz irgendwo im Netz liegen.

"Kurz" ist wörtlich gemeint: Instagram lädt das Bild beim Anlegen des
Beitrags herunter und hält danach seine eigene Kopie. Die Adresse wird
also nur für wenige Sekunden gebraucht. Deshalb wird jedes Bild mit
einer Verfallszeit hochgeladen - es verschwindet von selbst, statt sich
dort für immer zu sammeln.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Protocol

import httpx

from .aufbereiten import fuer_instagram

log = logging.getLogger(__name__)

# Einen Tag. Lange genug, dass ein fehlgeschlagener Beitrag im nächsten
# Zyklus erneut versucht werden kann, kurz genug, dass nichts liegenbleibt.
HALTBARKEIT_SEKUNDEN = 86_400


class Ablagefehler(RuntimeError):
    """Das Bild ließ sich nicht öffentlich ablegen."""


class Bildablage(Protocol):
    name: str

    def lade_hoch(self, bild: Path) -> str:
        """Legt das Bild ab und gibt seine öffentliche Adresse zurück."""
        ...


class ImgbbAblage:
    """imgbb: ein Schlüssel, ein Aufruf, eine Adresse zurück.

    Bewusst ein Dienst mit Verfallszeit statt eines eigenen Speichers:
    Was hier landet, ist ohnehin schon veröffentlicht - es ist genau das
    Bild, das gleich auf Instagram steht. Dauerhaft liegen bleiben muss
    es trotzdem nicht.
    """

    name = "imgbb"
    ADRESSE = "https://api.imgbb.com/1/upload"

    def __init__(self, token: str, *, timeout: float = 60.0) -> None:
        self.token = token
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def lade_hoch(self, bild: Path) -> str:
        if not bild.is_file():
            raise Ablagefehler(f"Das Bild gibt es nicht: {bild}")

        # Instagram nimmt nur JPEG in einem bestimmten Rahmen an. Der
        # lokale Entwurf bleibt, wie er ist - nur was hinausgeht, wird
        # umgerechnet.
        daten = fuer_instagram(bild)

        antwort = self.client.post(
            self.ADRESSE,
            params={"key": self.token, "expiration": str(HALTBARKEIT_SEKUNDEN)},
            data={"image": base64.b64encode(daten).decode(), "name": bild.stem},
        )
        if antwort.status_code >= 400:
            raise Ablagefehler(_lesbar(antwort))

        daten = antwort.json()
        adresse = (daten.get("data") or {}).get("url")
        if not adresse:
            raise Ablagefehler(f"Keine Adresse zurückbekommen: {str(daten)[:200]}")

        log.info("Bild abgelegt: %s", adresse)
        return str(adresse)


def _lesbar(antwort: httpx.Response) -> str:
    if antwort.status_code in (400, 401, 403):
        return (
            "Der Bildspeicher weist den Schlüssel zurück. Trag ihn neu ein "
            "mit `insta-agent ablage`."
        )
    if antwort.status_code == 413:
        return "Das Bild ist zu groß für den Bildspeicher."
    if antwort.status_code == 429:
        return "Zu viele Uploads auf einmal. Beim nächsten Zyklus wieder."
    return f"Der Bildspeicher antwortete mit {antwort.status_code}."


ABLAGEN: dict[str, type] = {"imgbb": ImgbbAblage}


def baue_ablage(anbieter: str, token: str | None) -> Bildablage | None:
    """None heißt: kein öffentlicher Platz eingerichtet - dann wird nicht gepostet."""
    if not token:
        return None
    klasse = ABLAGEN.get(anbieter)
    if klasse is None:
        log.warning("Unbekannter Bildspeicher %r", anbieter)
        return None
    return klasse(token)
