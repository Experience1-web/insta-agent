"""Einen öffentlichen Platz für die fertigen Bilder.

Instagram nimmt keine Datei entgegen. Es bekommt eine Adresse und holt
sich das Bild selbst. Der Rechner des Betreibers ist von außen nicht
erreichbar, also muss das Bild kurz irgendwo im Netz liegen.

"Kurz" ist wörtlich gemeint: Instagram lädt das Bild beim Anlegen des
Beitrags herunter und hält danach seine eigene Kopie. Die Adresse wird
also nur für wenige Sekunden gebraucht. Deshalb wird jedes Bild mit
einer Verfallszeit hochgeladen - es verschwindet von selbst, statt sich
dort für immer zu sammeln.

Wichtig ist die Wahl des Dienstes, und zwar aus einem Grund, der nirgends
dokumentiert steht: Instagram holt das Bild mit einem eigenen Abholer.
Manche Bildspeicher sind bei Meta gesperrt - dann kommt der Abholer nicht
an die Datei und Instagram meldet "Only photo or video can be accepted as
media type" (Fehler 9004). Die Meldung zeigt auf das Bild, gemeint ist
aber die Adresse. Deshalb gibt es hier mehrere Dienste und nicht einen:
Wird eine Adresse abgelehnt, wird dieselbe Datei beim naechsten Dienst
abgelegt und noch einmal versucht.
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


class _CatboxArtig:
    """Catbox und Litterbox: ein Aufruf, kein Schluessel, Adresse als Klartext.

    Kein Konto, kein Schluessel - das ist hier kein Geiz, sondern der
    Unterschied zwischen "laeuft" und "der Betreiber muss sich erst
    irgendwo anmelden". Der Dienst gibt die fertige Adresse als nackten
    Text zurueck, kein JSON.
    """

    name = "catbox"
    ADRESSE = "https://catbox.moe/user/api.php"
    # Litterbox will zusaetzlich wissen, wie lange die Datei liegen soll.
    HALTBARKEIT: str | None = None

    def __init__(self, token: str | None = None, *, timeout: float = 60.0) -> None:
        # Der Schluessel wird nicht gebraucht; das Argument gibt es nur,
        # damit alle Ablagen gleich gebaut werden koennen.
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def lade_hoch(self, bild: Path) -> str:
        if not bild.is_file():
            raise Ablagefehler(f"Das Bild gibt es nicht: {bild}")

        felder = {"reqtype": "fileupload"}
        if self.HALTBARKEIT:
            felder["time"] = self.HALTBARKEIT

        antwort = self.client.post(
            self.ADRESSE,
            data=felder,
            files={"fileToUpload": (f"{bild.stem}.jpg", fuer_instagram(bild), "image/jpeg")},
        )
        if antwort.status_code >= 400:
            raise Ablagefehler(_lesbar(antwort))

        adresse = antwort.text.strip()
        if not adresse.startswith("https://"):
            raise Ablagefehler(f"Keine Adresse zurückbekommen: {adresse[:200]}")

        log.info("Bild abgelegt: %s", adresse)
        return str(adresse)


class CatboxAblage(_CatboxArtig):
    """Bleibt liegen, bis jemand es loescht."""

    name = "catbox"


class LitterboxAblage(_CatboxArtig):
    """Dasselbe, nur mit Verfallszeit - deshalb die erste Wahl."""

    name = "litterbox"
    ADRESSE = "https://litterbox.catbox.moe/resources/internals/api.php"
    HALTBARKEIT = "24h"


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


ABLAGEN: dict[str, type] = {
    "litterbox": LitterboxAblage,
    "catbox": CatboxAblage,
    "imgbb": ImgbbAblage,
}

# Diese Dienste brauchen kein Konto und keinen Schlüssel.
OHNE_SCHLUESSEL = frozenset({"litterbox", "catbox"})

# Reihenfolge, in der weitergesucht wird, wenn Instagram eine Adresse
# ablehnt. imgbb steht bewusst hinten: Meta lehnt Adressen von dort
# zuverlässig ab, und zwar mit einer Meldung, die auf das Bild zeigt.
KETTE = ("litterbox", "catbox", "imgbb")

# Dienste, von denen Meta erwiesenermaßen nicht abholt. Sie bleiben in der
# Kette - vielleicht ändert sich das wieder - aber sie kommen nie zuerst
# dran, auch wenn sie eingestellt sind. Sonst kostet jeder Beitrag erst
# einen Fehlschlag.
NIE_ZUERST = frozenset({"imgbb"})


def baue_ablage(anbieter: str, token: str | None) -> Bildablage | None:
    """None heißt: kein öffentlicher Platz eingerichtet - dann wird nicht gepostet."""
    klasse = ABLAGEN.get(anbieter)
    if klasse is None:
        log.warning("Unbekannter Bildspeicher %r", anbieter)
        return None
    if anbieter not in OHNE_SCHLUESSEL and not token:
        return None
    return klasse(token)


def baue_ablagen(anbieter: str, token: str | None) -> list[Bildablage]:
    """Der eingestellte Dienst zuerst, danach die übrigen als Rückfallebene.

    Ein einzelner Dienst ist ein einzelner Punkt, an dem alles stehen
    bleibt - und ob Meta eine Adresse annimmt, lässt sich vorher nicht
    prüfen. Also wird der Reihe nach versucht.
    """
    if anbieter in NIE_ZUERST:
        reihenfolge = [*KETTE, anbieter]
    else:
        reihenfolge = [anbieter, *(a for a in KETTE if a != anbieter)]
    # Doppelte fliegen raus, die erste Nennung gewinnt.
    reihenfolge = list(dict.fromkeys(reihenfolge))
    gebaut: list[Bildablage] = []
    for name in reihenfolge:
        ablage = baue_ablage(name, token)
        if ablage is not None:
            gebaut.append(ablage)
    return gebaut
