"""Bilder erzeugen lassen - beim Anbieter, den der Betreiber bezahlt.

Claude macht keine Bilder. Für einen bildgetriebenen Account braucht es
deshalb einen zweiten Dienst und einen zweiten Schlüssel. Das ist keine
Bequemlichkeitsentscheidung, sondern eine Tatsache der Lage.

Der Agent schreibt den Prompt, dieser Baustein holt das Bild, und die
Kosten landen in derselben Kasse wie das Denken - sonst wüsste der Agent
nicht, was ein Beitrag ihn wirklich kostet.

Schlägt die Erzeugung fehl, wird das nirgends verschwiegen: Der Aufrufer
bekommt None und nimmt die typografische Fassung, die immer funktioniert.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

# So lange warten wir insgesamt auf ein Bild. Flux braucht je nach Modell
# 3 bis 30 Sekunden; wer länger wartet, blockiert den ganzen Zyklus.
GEDULD_SEKUNDEN = 120.0


class Bildfehler(RuntimeError):
    """Der Bilddienst konnte kein Bild liefern."""


class Bildgenerator(Protocol):
    """Was ein Anbieter können muss, damit der Zyklus ihn nutzen kann."""

    name: str

    def erzeuge(self, prompt: str, ziel: Path) -> Path:
        """Erzeugt ein Bild und legt es unter `ziel` ab. Wirft bei Fehlschlag."""
        ...


class ReplicateGenerator:
    """Flux über Replicate.

    Replicate hostet die Flux-Modelle von Black Forest Labs. Ein Schlüssel,
    ein Guthaben, Abrechnung pro Bild. Mit dem Kopfzeilenfeld `Prefer: wait`
    antwortet der Dienst direkt mit dem fertigen Bild, statt uns eine
    Warteschlange nachverfolgen zu lassen - erst wenn das nicht reicht,
    fragen wir nach.
    """

    name = "replicate"

    def __init__(self, token: str, modell: str, *, timeout: float = 60.0) -> None:
        self.token = token
        self.modell = modell
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self.client.close()

    def erzeuge(self, prompt: str, ziel: Path) -> Path:
        antwort = self.client.post(
            f"https://api.replicate.com/v1/models/{self.modell}/predictions",
            headers={"Prefer": "wait"},
            json={
                "input": {
                    "prompt": prompt,
                    "aspect_ratio": "9:16",
                    "output_format": "png",
                }
            },
        )
        if antwort.status_code >= 400:
            raise Bildfehler(_lesbarer_fehler(antwort))

        vorhersage = antwort.json()
        vorhersage = self._warte_bis_fertig(vorhersage)

        url = _erste_bildadresse(vorhersage.get("output"))
        if not url:
            raise Bildfehler(f"Der Dienst lieferte kein Bild: {vorhersage.get('status')}")

        return self._lade_herunter(url, ziel)

    def _warte_bis_fertig(self, vorhersage: dict) -> dict:
        """Fragt nach, solange der Dienst noch rechnet."""
        frist = time.monotonic() + GEDULD_SEKUNDEN
        while vorhersage.get("status") in ("starting", "processing"):
            if time.monotonic() > frist:
                raise Bildfehler("Der Bilddienst hat zu lange gebraucht.")
            nachfrage = (vorhersage.get("urls") or {}).get("get")
            if not nachfrage:
                raise Bildfehler("Der Dienst nannte keine Adresse zum Nachfragen.")
            time.sleep(2.0)
            antwort = self.client.get(nachfrage)
            if antwort.status_code >= 400:
                raise Bildfehler(_lesbarer_fehler(antwort))
            vorhersage = antwort.json()

        if vorhersage.get("status") != "succeeded":
            fehler = vorhersage.get("error") or vorhersage.get("status")
            raise Bildfehler(f"Die Bilderzeugung schlug fehl: {fehler}")
        return vorhersage

    def hol_bytes(self, url: str) -> bytes:
        """Lädt das fertige Bild - bewusst ohne unseren Schlüssel.

        Die Adresse zeigt auf einen Auslieferungsdienst, nicht auf den
        Anbieter. Den Zugangsschlüssel dorthin mitzuschicken, würde ihn an
        einen Dritten geben, der ihn nicht braucht.
        """
        with httpx.Client(timeout=60.0, follow_redirects=True) as roh:
            antwort = roh.get(url)
        if antwort.status_code >= 400:
            raise Bildfehler(f"Das fertige Bild war nicht abrufbar ({antwort.status_code}).")
        return antwort.content

    def _lade_herunter(self, url: str, ziel: Path) -> Path:
        inhalt = self.hol_bytes(url)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(inhalt)
        log.info("Bild erzeugt: %s", ziel.name)
        return ziel


def _erste_bildadresse(ausgabe: object) -> str | None:
    """Die Modelle antworten mal mit einer Liste, mal mit einer Zeichenkette."""
    if isinstance(ausgabe, str):
        return ausgabe
    if isinstance(ausgabe, list) and ausgabe and isinstance(ausgabe[0], str):
        return ausgabe[0]
    return None


def _lesbarer_fehler(antwort: httpx.Response) -> str:
    """Macht aus einem HTTP-Fehler einen Satz, der dem Betreiber hilft."""
    if antwort.status_code == 401:
        return (
            "Der Bilddienst weist den Schlüssel zurück. Trag ihn neu ein mit "
            "`insta-agent bilder`."
        )
    if antwort.status_code == 402:
        return "Das Guthaben beim Bilddienst ist aufgebraucht."
    if antwort.status_code == 404:
        return "Dieses Bildmodell gibt es nicht. Prüf den Modellnamen."
    if antwort.status_code == 429:
        return "Zu viele Anfragen an den Bilddienst. Beim nächsten Zyklus wieder."
    try:
        detail = antwort.json().get("detail") or antwort.text
    except Exception:  # noqa: BLE001 - die Fehlermeldung darf nie selbst scheitern
        detail = antwort.text
    return f"Der Bilddienst antwortete mit {antwort.status_code}: {str(detail)[:200]}"


ANBIETER: dict[str, type] = {"replicate": ReplicateGenerator}


def baue_generator(anbieter: str, token: str | None, modell: str) -> Bildgenerator | None:
    """Gibt None zurück, wenn kein Schlüssel hinterlegt ist - das ist kein Fehler."""
    if not token:
        return None
    klasse = ANBIETER.get(anbieter)
    if klasse is None:
        log.warning("Unbekannter Bildanbieter %r - es bleibt bei der Typografie", anbieter)
        return None
    return klasse(token, modell)
