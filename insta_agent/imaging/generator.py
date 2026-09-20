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


class LokalerGenerator:
    """Ein Bildmodell, das auf dem eigenen Rechner läuft.

    Der einzige wirklich kostenlose Weg: Du zahlst mit deiner Grafikkarte
    und etwas Strom statt mit Guthaben. Voraussetzung ist ein laufendes
    Stable-Diffusion-Webinterface mit eingeschalteter Programmierschnittstelle
    - AUTOMATIC1111, Forge oder SD.Next sprechen alle dieselbe Sprache.

    Bewusst diese Schnittstelle und nicht die von ComfyUI: Hier genügt ein
    Prompt, dort müsste ein ganzer Arbeitsablauf als Datenstruktur
    mitgeschickt werden, der bei jedem Modellwechsel anders aussieht.
    """

    name = "lokal"

    def __init__(self, adresse: str, modell: str = "", *, timeout: float = 300.0) -> None:
        # Ein Bild auf einer Mittelklasse-Karte dauert 20 bis 60 Sekunden,
        # beim ersten Mal deutlich länger, weil das Modell geladen wird.
        self.adresse = (adresse or "http://127.0.0.1:7860").rstrip("/")
        self.modell = modell
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def erzeuge(self, prompt: str, ziel: Path) -> Path:
        # Genau 9:16 und durch 8 teilbar, sonst lehnt das Modell ab. Rund
        # 1,1 Millionen Bildpunkte - das ist der Bereich, in dem SDXL
        # zuverlaessig arbeitet. Groesser wird langsam und instabil.
        breite, hoehe = 792, 1408
        nutzlast: dict[str, object] = {
            "prompt": prompt,
            "negative_prompt": "text, watermark, logo, signature, letters, caption",
            "width": breite,
            "height": hoehe,
            "steps": 28,
            "cfg_scale": 5.0,
            "sampler_name": "DPM++ 2M",
        }
        if self.modell:
            nutzlast["override_settings"] = {"sd_model_checkpoint": self.modell}

        try:
            antwort = self.client.post(f"{self.adresse}/sdapi/v1/txt2img", json=nutzlast)
        except httpx.ConnectError as exc:
            raise Bildfehler(
                f"Unter {self.adresse} antwortet nichts. Läuft das Bildprogramm, "
                "und ist es mit --api gestartet?"
            ) from exc
        except httpx.ReadTimeout as exc:
            raise Bildfehler(
                "Der eigene Rechner hat zu lange gebraucht. Ohne passende "
                "Grafikkarte dauert ein Bild viele Minuten."
            ) from exc

        if antwort.status_code == 404:
            raise Bildfehler(
                "Das Bildprogramm kennt diese Schnittstelle nicht. Starte es "
                "mit --api (AUTOMATIC1111, Forge oder SD.Next)."
            )
        if antwort.status_code >= 400:
            raise Bildfehler(_lesbarer_fehler(antwort))

        bilder = antwort.json().get("images") or []
        if not bilder:
            raise Bildfehler("Das Bildprogramm lieferte kein Bild zurück.")

        import base64

        ziel.parent.mkdir(parents=True, exist_ok=True)
        # Manche Fassungen hängen einen Datentyp-Vorspann an.
        roh = bilder[0].split(",", 1)[-1]
        ziel.write_bytes(base64.b64decode(roh))
        log.info("Bild lokal erzeugt: %s", ziel.name)
        return ziel


class GeminiGenerator:
    """Googles Bildmodell über die Gemini-Schnittstelle.

    Interessant, weil Google ein kostenloses Kontingent anbietet: Für ein
    paar Bilder am Tag genügt ein Schlüssel ohne Zahlungsdaten. Die
    Grenzen sind knapp und Google ändert sie - wer verlässlich viele
    Bilder braucht, ist beim bezahlten Weg oder lokal besser aufgehoben.

    Nicht jedes Bildmodell nimmt einen Seitenverhältnis-Wunsch entgegen.
    Wird er abgelehnt, fragen wir ohne ihn noch einmal - das Zuschneiden
    auf 9:16 passiert ohnehin beim Beschriften.
    """

    name = "gemini"
    BASIS = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, token: str, modell: str, *, timeout: float = 120.0) -> None:
        self.token = token
        self.modell = modell or "gemini-2.5-flash-image"
        self.client = httpx.Client(
            timeout=timeout, headers={"x-goog-api-key": token, "Content-Type": "application/json"}
        )

    def close(self) -> None:
        self.client.close()

    def _frage(self, prompt: str, mit_format: bool) -> httpx.Response:
        koerper: dict[str, object] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        if mit_format:
            koerper["generationConfig"]["imageConfig"] = {"aspectRatio": "9:16"}
        return self.client.post(f"{self.BASIS}/{self.modell}:generateContent", json=koerper)

    def erzeuge(self, prompt: str, ziel: Path) -> Path:
        antwort = self._frage(prompt, mit_format=True)
        if antwort.status_code == 400:
            # Ältere Bildmodelle kennen den Formatwunsch nicht.
            log.debug("Formatwunsch abgelehnt, frage ohne ihn nach")
            antwort = self._frage(prompt, mit_format=False)

        if antwort.status_code >= 400:
            grund = _gemini_fehler(antwort)
            if antwort.status_code == 429:
                raise KontingentErschoepft(grund)
            raise Bildfehler(grund)

        daten = _gemini_bilddaten(antwort.json())
        if daten is None:
            raise Bildfehler(
                "Google lieferte kein Bild. Oft heißt das, dass der Prompt "
                "abgelehnt wurde - formulier ihn harmloser."
            )

        import base64

        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(base64.b64decode(daten))
        log.info("Bild erzeugt (Gemini): %s", ziel.name)
        return ziel


def _gemini_bilddaten(antwort: dict) -> str | None:
    """Sucht die Bilddaten in der Antwort - sie stehen zwischen Textteilen."""
    for kandidat in antwort.get("candidates") or []:
        for teil in (kandidat.get("content") or {}).get("parts") or []:
            # Die Schnittstelle nutzt beide Schreibweisen.
            roh = teil.get("inlineData") or teil.get("inline_data")
            if roh and roh.get("data"):
                return roh["data"]
    return None


class KontingentErschoepft(Bildfehler):
    """Der Bilddienst kann heute nicht mehr - erst morgen wieder.

    Eigener Typ, weil daraus etwas folgt: Weitere Versuche im selben Lauf
    scheitern genauso, und alles, was nur fuer das Bild gedacht war, waere
    vergebene Arbeit.
    """


def _gemini_fehler(antwort: httpx.Response) -> str:
    if antwort.status_code in (401, 403):
        return (
            "Google weist den Schlüssel zurück. Leg einen neuen an unter "
            "aistudio.google.com und trag ihn mit `insta-agent bilder` ein."
        )
    if antwort.status_code == 429:
        return (
            "Das kostenlose Kontingent bei Google ist für heute aufgebraucht. "
            "Morgen geht es weiter - oder du hinterlegst dort Zahlungsdaten."
        )
    try:
        meldung = antwort.json().get("error", {}).get("message") or antwort.text
    except Exception:  # noqa: BLE001 - die Fehlermeldung darf nie selbst scheitern
        meldung = antwort.text
    return f"Google antwortete mit {antwort.status_code}: {str(meldung)[:200]}"



class LeonardoGenerator:
    """Leonardo.ai: FLUX und Phoenix über eine eigene Schnittstelle.

    Interessant, weil neue Zugänge ein Startguthaben von 5 USD bekommen,
    das nicht verfällt. Das reicht für etwa hundert Bilder auf einem
    Niveau, das Gemini Flash nicht erreicht - und danach kostet es Geld,
    statt einfach aufzuhören.

    Achtung, ein verbreiteter Irrtum: Die 150 Freitoken am Tag gehören zur
    Webseite, nicht zur Schnittstelle. Wer sie automatisch nutzen will,
    braucht einen Produktionsschlüssel, und der rechnet ab.

    Die Schnittstelle arbeitet in zwei Schritten: Auftrag abgeben, dann
    nachfragen, bis das Bild fertig ist.
    """

    name = "leonardo"
    BASIS = "https://cloud.leonardo.ai/api/rest/v1"

    # Phoenix 1.0 - Leonardos eigenes Modell, stark bei Licht und Material.
    # Ein anderes Modell wird als UUID in BILD_MODELL eingetragen; die
    # steht auf der Modellseite in Leonardos Oberfläche.
    STANDARDMODELL = "de7d3faf-762f-48e0-b3b7-9d0ac3a3fcf3"

    # Vielfache von 8, nah an 4:5. Grösser kostet mehr Token.
    BREITE, HOEHE = 832, 1040

    def __init__(self, token: str, modell: str = "", *, timeout: float = 60.0) -> None:
        self.token = token
        self.modell = modell.strip() or self.STANDARDMODELL
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self.client.close()

    def erzeuge(self, prompt: str, ziel: Path) -> Path:
        auftrag = self.client.post(
            f"{self.BASIS}/generations",
            json={
                "prompt": prompt[:1490],
                "modelId": self.modell,
                "width": self.BREITE,
                "height": self.HOEHE,
                "num_images": 1,
            },
        )
        if auftrag.status_code >= 400:
            raise _leonardo_fehler(auftrag)

        kennung = ((auftrag.json() or {}).get("sdGenerationJob") or {}).get("generationId")
        if not kennung:
            raise Bildfehler(f"Leonardo gab keinen Auftrag zurück: {auftrag.text[:200]}")

        url = self._warte_auf_bild(kennung)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(self.hol_bytes(url))
        log.info("Bild von Leonardo: %s", ziel)
        return ziel

    def _warte_auf_bild(self, kennung: str, *, versuche: int = 40, pause: float = 3.0) -> str:
        """Fragt nach, bis das Bild fertig ist."""
        for _ in range(versuche):
            antwort = self.client.get(f"{self.BASIS}/generations/{kennung}")
            if antwort.status_code >= 400:
                raise _leonardo_fehler(antwort)

            stand = (antwort.json() or {}).get("generations_by_pk") or {}
            zustand = stand.get("status")
            if zustand == "COMPLETE":
                bilder = stand.get("generated_images") or []
                if bilder and bilder[0].get("url"):
                    return bilder[0]["url"]
                raise Bildfehler("Leonardo meldet fertig, liefert aber kein Bild.")
            if zustand == "FAILED":
                raise Bildfehler("Leonardo konnte das Bild nicht erzeugen.")
            time.sleep(pause)

        raise Bildfehler("Leonardo wurde nicht rechtzeitig fertig.")

    def hol_bytes(self, url: str) -> bytes:
        """Eigener Aufruf ohne Schlüssel: Der gehört nicht zum Bildspeicher."""
        with httpx.Client(timeout=60.0) as roh:
            antwort = roh.get(url)
            antwort.raise_for_status()
            return antwort.content


def _leonardo_fehler(antwort: httpx.Response) -> Bildfehler:
    if antwort.status_code in (401, 403):
        return Bildfehler(
            "Leonardo weist den Schlüssel zurück. Er muss ein Produktions-"
            "schlüssel sein (API Access), nicht der Zugang zur Webseite."
        )
    if antwort.status_code == 402:
        return Bildfehler(
            "Das Guthaben bei Leonardo ist aufgebraucht. Unter app.leonardo.ai "
            "nachlegen - oder mit `insta-agent bilder` auf einen anderen "
            "Dienst wechseln."
        )
    if antwort.status_code == 429:
        return Bildfehler("Zu viele Aufträge bei Leonardo auf einmal. Gleich nochmal.")
    if antwort.status_code == 400:
        return Bildfehler(
            f"Leonardo lehnt den Auftrag ab: {antwort.text[:200]}\n"
            "Meist stimmt die Modell-Kennung nicht. Sie steht als UUID auf der "
            "Modellseite und gehört in `insta-agent bilder`."
        )
    return Bildfehler(f"Leonardo antwortete mit {antwort.status_code}: {antwort.text[:200]}")


ANBIETER: dict[str, type] = {
    "gemini": GeminiGenerator,
    "replicate": ReplicateGenerator,
    "lokal": LokalerGenerator,
    "leonardo": LeonardoGenerator,
}

# Der lokale Weg braucht keinen Schlüssel, sondern eine Adresse.
OHNE_SCHLUESSEL = {"lokal"}


def baue_generator(anbieter: str, token: str | None, modell: str) -> Bildgenerator | None:
    """Baut den passenden Generator, oder None.

    None ist kein Fehler: Ohne eingerichteten Bilddienst bleibt es bei der
    typografischen Fassung, und der Zyklus läuft genauso durch.

    Beim lokalen Weg steht in `token` die Adresse des eigenen
    Bildprogramms statt eines Schlüssels - er kostet nichts, also gibt es
    auch nichts zu authentifizieren.
    """
    klasse = ANBIETER.get(anbieter)
    if klasse is None:
        log.warning("Unbekannter Bildanbieter %r - es bleibt bei der Typografie", anbieter)
        return None
    if anbieter in OHNE_SCHLUESSEL:
        return klasse(token or "http://127.0.0.1:7860", modell)
    if not token:
        return None
    return klasse(token, modell)
