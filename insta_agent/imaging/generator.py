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

import base64
import logging
import random
import time
from pathlib import Path
from typing import Any, Protocol

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


# Woran man ein SDXL-Modell erkennt. Nicht schön, aber es gibt kein Feld
# in der Schnittstelle, das die Bauart verrät - und die Dateinamen tragen
# das "XL" praktisch ausnahmslos, weil die Modellbauer selbst zwischen
# beiden Welten unterscheiden müssen.
_XL_SPUREN = ("xl", "pony", "illustrious", "noobai")


def modellart(modellname: str) -> str:
    """"flux", "sdxl" oder "sd15" - die drei Welten mit eigenen Regeln.

    Das ist kein Feinschliff, sondern entscheidet über Bild oder Matsch.
    FLUX braucht CFG 1 und keine Negativführung, SDXL CFG 4 bis 7, SD 1.5
    CFG 7 und vor allem eine viel kleinere Grundfläche. Wer ein
    SD-1.5-Modell auf SDXL-Maße loslässt, bekommt doppelte Köpfe.

    Im Zweifel SD 1.5: Das ist die vorsichtigere Annahme. Ein SDXL-Modell
    auf SD-1.5-Maßen wird nur etwas flau, umgekehrt wird es unbrauchbar.
    """
    klein = (modellname or "").casefold()
    if "flux" in klein:
        return "flux"
    if any(spur in klein for spur in _XL_SPUREN):
        return "sdxl"
    return "sd15"


def ist_flux(modellname: str) -> bool:
    """Ob dieser Modellname nach FLUX aussieht."""
    return modellart(modellname) == "flux"


# Wie groß das Modell malt, bevor hochskaliert wird. Nicht frei wählbar:
# Jedes Modell ist auf eine Fläche trainiert, und deutlich darüber hinaus
# entstehen doppelte Köpfe und verdrehte Körper. SD 1.5 kennt 512er
# Kanten, deshalb 512x768 und danach das Hochrechnen - nicht umgekehrt.
GRUNDMASSE: dict[str, tuple[int, int]] = {
    "flux": (792, 1408),
    "sdxl": (792, 1408),
    "sd15": (512, 768),
}

# SD 1.5 braucht eine echte Negativführung, sonst sieht man ihm das Alter
# an. Bei SDXL und FLUX reicht wenig bis nichts.
_NEGATIV_SD15 = (
    "text, watermark, logo, signature, letters, caption, "
    "lowres, blurry, out of focus, jpeg artifacts, worst quality, "
    "deformed, disfigured, bad anatomy, extra limbs, extra fingers, "
    "mutated hands, cropped, out of frame"
)


def werte_fuer(modellname: str, *, art: str = "") -> dict[str, object]:
    """Schritte, CFG und Sampler, die zu diesem Modell passen.

    `art` übergeht die Erkennung am Namen - gedacht für den Fall, dass
    der Betreiber es besser weiß als der Dateiname.
    """
    art = art if art in GRUNDMASSE else modellart(modellname)
    if art == "flux":
        # FLUX kennt keine klassische Negativführung und arbeitet ohne
        # CFG. Das Negativfeld bleibt leer, statt wirkungslos mitzulaufen.
        return {
            "negative_prompt": "",
            "steps": 20,
            "cfg_scale": 1.0,
            "sampler_name": "Euler",
        }
    if art == "sd15":
        # 512x768 ist für Instagram zu klein, deshalb rechnet das
        # Bildprogramm im zweiten Durchgang selbst auf 1024x1536 hoch.
        # Das kostet etwa die Hälfte der Zeit noch einmal und ist trotzdem
        # der einzige Weg, mit SD 1.5 auf brauchbare Kantenlängen zu
        # kommen, ohne die Bildkomposition zu zerstören.
        return {
            "negative_prompt": _NEGATIV_SD15,
            "steps": 30,
            "cfg_scale": 7.0,
            "sampler_name": "DPM++ 2M Karras",
            "enable_hr": True,
            "hr_scale": 2.0,
            "hr_upscaler": "R-ESRGAN 4x+",
            "hr_second_pass_steps": 12,
            "denoising_strength": 0.4,
        }
    return {
        "negative_prompt": "text, watermark, logo, signature, letters, caption",
        "steps": 28,
        "cfg_scale": 5.0,
        "sampler_name": "DPM++ 2M",
    }


def laeuft_auf_der_grafikkarte(adresse: str, client: httpx.Client) -> bool | None:
    """Ob das Bildprogramm die Grafikkarte benutzt - oder nur den Prozessor.

    Der teuerste stille Fehler beim eigenen Rechner: Wird PyTorch in der
    Prozessorfassung installiert, läuft alles - nur eben auf der CPU. Ein
    Bild dauert dann nicht eine Minute, sondern zwanzig. Im Protokoll
    steht es als beiläufige Warnung zwischen hundert anderen Zeilen, und
    wer das nicht kennt, sucht den Fehler wochenlang woanders.

    None heisst: nicht feststellbar. Das ist kein Grund zur Sorge, nur
    kein Beweis.
    """
    try:
        daten = client.get(f"{adresse}/sdapi/v1/memory").json()
    except Exception:  # noqa: BLE001 - aeltere Fassungen kennen das nicht
        return None
    cuda = daten.get("cuda")
    if not isinstance(cuda, dict):
        return None
    if cuda.get("error"):
        return False
    return bool(cuda.get("system") or cuda.get("active"))


def frage_lokal_ab(
    adresse: str, *, timeout: float = 10.0
) -> tuple[list[str], str, bool | None]:
    """Welche Modelle das eigene Bildprogramm kennt, was läuft, und worauf.

    Gedacht für die Einrichtung: Wer eine Adresse eintippt, soll sofort
    erfahren, ob dort etwas antwortet, statt es beim ersten Beitrag zu
    merken. Wirft `Bildfehler` mit einem Satz, der sagt, was zu tun ist.

    Der dritte Rückgabewert sagt, ob die Grafikkarte benutzt wird: False
    heisst Prozessor, und das ändert alles.
    """
    adresse = (adresse or "").rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            antwort = client.get(f"{adresse}/sdapi/v1/sd-models")
            if antwort.status_code == 404:
                raise Bildfehler(
                    "Dort läuft etwas, aber es kennt diese Schnittstelle nicht. "
                    "Das Bildprogramm braucht den Schalter --api: in Stability "
                    "Matrix beim Zahnrad neben 'Launch' unter 'Extra Launch "
                    "Arguments' eintragen, sonst in webui-user.bat."
                )
            antwort.raise_for_status()
            modelle = [str(m.get("model_name") or m.get("title", "")) for m in antwort.json()]

            geladen = ""
            try:
                einst = client.get(f"{adresse}/sdapi/v1/options").json()
                geladen = str(einst.get("sd_model_checkpoint") or "")
            except Exception:  # noqa: BLE001 - die Modellliste reicht schon
                pass
            auf_karte = laeuft_auf_der_grafikkarte(adresse, client)
    except httpx.ConnectError as exc:
        raise Bildfehler(
            f"Unter {adresse} antwortet nichts. Läuft das Bildprogramm, und "
            "ist es mit --api gestartet?"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise Bildfehler(_lesbarer_fehler(exc.response)) from exc
    except httpx.TimeoutException as exc:
        raise Bildfehler(
            "Keine Antwort innerhalb von zehn Sekunden. Startet das "
            "Bildprogramm gerade noch?"
        ) from exc

    return [m for m in modelle if m], geladen, auf_karte


def _route_fehlt(antwort: httpx.Response) -> bool:
    """Ob die 404 heisst "diesen Weg gibt es nicht" - und nicht etwas anderes.

    Die Unterscheidung muss sein: Das Bildprogramm antwortet auch dann
    mit 404, wenn der Sampler unbekannt ist. Wer das mit der fehlenden
    Schnittstelle verwechselt, schickt den Betreiber zum Zahnrad, obwohl
    dort alles richtig steht.
    """
    if antwort.status_code != 404:
        return False
    try:
        detail = str(antwort.json().get("detail") or "")
    except Exception:  # noqa: BLE001 - ohne JSON ist es kein API-Fehler
        return True
    return detail.strip().casefold() in ("", "not found")


def _ohne_stolperstein(
    koerper: dict[str, object], antwort: httpx.Response
) -> dict[str, object] | None:
    """Ein zweiter, bescheidenerer Versuch - oder None, wenn keiner hilft."""
    text = f"{antwort.text}".casefold()
    zweit = dict(koerper)

    if "out of memory" in text or "outofmemory" in text:
        if not zweit.get("enable_hr"):
            return None
        # Der zweite Durchgang sprengt den Speicher, der erste nicht.
        for feld in ("enable_hr", "hr_scale", "hr_upscaler", "hr_second_pass_steps"):
            zweit.pop(feld, None)
        log.warning("Grafikspeicher reichte nicht zum Hochrechnen - Bild bleibt klein.")
        return zweit

    sampler = str(zweit.get("sampler_name") or "")
    if "sampler" in text and "Karras" in sampler:
        zweit["sampler_name"] = sampler.replace(" Karras", "").strip()
        log.warning("Sampler %s unbekannt - weiter mit %s.", sampler, zweit["sampler_name"])
        return zweit

    return None


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

    def __init__(
        self,
        adresse: str,
        modell: str = "",
        *,
        art: str = "",
        timeout: float = 300.0,
    ) -> None:
        # Ein Bild auf einer Mittelklasse-Karte dauert 20 bis 60 Sekunden,
        # beim ersten Mal deutlich länger, weil das Modell geladen wird.
        # Auf einer alten Karte mit SD 1.5 und Hochrechnen eher zwei bis
        # vier Minuten - deshalb die grosszügige Frist.
        self.adresse = (adresse or "http://127.0.0.1:7860").rstrip("/")
        self.modell = modell
        # Leer heisst: am Namen erkennen. Sonst gilt, was eingestellt ist.
        self.art = art.strip().casefold() if art.strip().casefold() in GRUNDMASSE else ""
        self.client = httpx.Client(timeout=timeout)

    @property
    def bauart(self) -> str:
        """Welche Regeln gelten - eingestellt schlägt erkannt."""
        return self.art or modellart(self.modell)

    def close(self) -> None:
        self.client.close()

    def _male(self, nutzlast: dict[str, object]) -> httpx.Response:
        """Schickt den Auftrag ab - und faengt die zwei haeufigen Absagen ab.

        Zwei Dinge gehen auf fremden Rechnern regelmaeszig schief, und
        beide sind kein Grund, den ganzen Beitrag fallen zu lassen:

        Der Sampler heiszt nicht ueberall gleich. Aeltere Fassungen kennen
        "DPM++ 2M Karras", neuere haben die Karras-Variante abgetrennt.
        Wird er abgelehnt, fragen wir ohne den Zusatz noch einmal.

        Und der Speicher der Grafikkarte reicht nicht fuer den zweiten
        Durchgang. Dann malen wir ohne Hochrechnen - ein kleineres Bild
        ist besser als keines.
        """
        versuche: list[dict[str, object]] = [nutzlast]
        for versuch, koerper in enumerate(versuche):
            try:
                antwort = self.client.post(
                    f"{self.adresse}/sdapi/v1/txt2img", json=koerper
                )
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

            if antwort.status_code < 400:
                return antwort

            if versuch == 0:
                ausweg = _ohne_stolperstein(koerper, antwort)
                if ausweg is not None:
                    versuche.append(ausweg)
                    continue
            if _route_fehlt(antwort):
                raise Bildfehler(
                    "Das Bildprogramm kennt diese Schnittstelle nicht. Es braucht "
                    "den Schalter --api: in Stability Matrix beim Zahnrad neben "
                    "'Launch' unter 'Extra Launch Arguments', sonst in "
                    "webui-user.bat."
                )
            raise Bildfehler(_lesbarer_fehler(antwort))

        raise Bildfehler("Das Bildprogramm lieferte kein Bild zurück.")

    def erzeuge(self, prompt: str, ziel: Path) -> Path:
        # Die Grundflaeche richtet sich nach der Bauart des Modells, nicht
        # nach dem Wunschformat: Wer SD 1.5 auf SDXL-Maszen malen laesst,
        # bekommt doppelte Koepfe. Auf das Endformat beschnitten wird
        # ohnehin erst beim Beschriften.
        breite, hoehe = GRUNDMASSE[self.bauart]
        nutzlast: dict[str, object] = {
            "prompt": prompt,
            "width": breite,
            "height": hoehe,
            **werte_fuer(self.modell, art=self.bauart),
        }
        if self.modell:
            nutzlast["override_settings"] = {"sd_model_checkpoint": self.modell}

        antwort = self._male(nutzlast)

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



class PollinationsGenerator:
    """Pollinations: FLUX ohne Konto, ohne Schlüssel, ohne Guthaben.

    Der ganze Aufruf ist eine Adresse: Prompt hinein, Bild heraus. Damit
    ist es der einzige Weg, der sofort funktioniert - keine Anmeldung, kein
    Schlüssel, nichts einzurichten.

    Zwei Dinge dazu, damit niemand sich täuscht: Ohne Konto kann ein
    Wasserzeichen im Bild landen (mit `token` fällt es weg, kostenlos zu
    bekommen). Und ein Dienst ohne Anmeldung gibt keine Zusagen - wenn er
    überlastet ist, dauert es oder es kommt nichts. Deshalb bleibt die
    typografische Fassung die Rückfallebene.
    """

    name = "pollinations"
    ADRESSE = "https://image.pollinations.ai/prompt"

    # 4:5 für den Feed, beide Maße durch 8 teilbar.
    BREITE, HOEHE = 864, 1080

    # Ein Bild kann eine Weile brauchen - der Dienst rechnet beim Abruf.
    def __init__(self, token: str | None = None, modell: str = "", *, timeout: float = 180.0) -> None:
        self.token = (token or "").strip()
        self.modell = modell.strip() or "flux"
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def erzeuge(self, prompt: str, ziel: Path) -> Path:
        from urllib.parse import quote

        params: dict[str, Any] = {
            "model": self.modell,
            "width": self.BREITE,
            "height": self.HOEHE,
            # Ohne das kommt bei gleichem Prompt immer dasselbe Bild - und
            # "Bild neu" wäre wirkungslos.
            "seed": random.randint(1, 2_000_000_000),
            "nologo": "true",
        }
        if self.token:
            params["token"] = self.token

        antwort = self.client.get(f"{self.ADRESSE}/{quote(prompt[:1800], safe='')}", params=params)
        if antwort.status_code >= 400:
            raise _pollinations_fehler(antwort)

        typ = antwort.headers.get("content-type", "")
        if not typ.startswith("image/"):
            raise Bildfehler(
                f"Pollinations schickte kein Bild, sondern {typ or 'nichts Erkennbares'}: "
                f"{antwort.text[:160]}"
            )

        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(antwort.content)
        log.info("Bild von Pollinations: %s", ziel)
        return ziel


def _pollinations_fehler(antwort: httpx.Response) -> Bildfehler:
    if antwort.status_code == 429:
        return Bildfehler(
            "Pollinations ist gerade überlastet oder das Kontingent ist erreicht. "
            "Später nochmal - es bleibt solange bei der Typografie."
        )
    if antwort.status_code in (401, 403):
        return Bildfehler("Pollinations weist den Zugang zurück.")
    return Bildfehler(f"Pollinations antwortete mit {antwort.status_code}.")


class CloudflareGenerator:
    """FLUX.1 schnell über Cloudflare Workers AI.

    Cloudflare gibt jedem Konto ein Tageskontingent umsonst - genug für
    etwa 170 Bilder am Tag. Das ist mehr, als dieser Account je brauchen
    wird, und es setzt sich jeden Tag zurück.

    Gebraucht werden zwei Angaben statt einer: die Kontonummer und ein
    Zugriffsschlüssel. Beide stehen im Cloudflare-Dashboard.
    """

    name = "cloudflare"
    MODELL = "@cf/black-forest-labs/flux-1-schnell"

    def __init__(self, token: str, modell: str = "", *, timeout: float = 120.0) -> None:
        # In `token` steht "Kontonummer:Schlüssel" - eine Einstellung, zwei
        # Angaben. Ein zweites Feld in der .env wäre eine Stelle mehr, an
        # der man sich vertun kann.
        konto, _, schluessel = token.partition(":")
        self.konto = konto.strip()
        self.schluessel = schluessel.strip()
        self.modell = modell.strip() or self.MODELL
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.schluessel}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self.client.close()

    def erzeuge(self, prompt: str, ziel: Path) -> Path:
        if not self.konto or not self.schluessel:
            raise Bildfehler(
                "Für Cloudflare braucht es Kontonummer und Schlüssel, getrennt "
                "durch einen Doppelpunkt. Neu eintragen mit `insta-agent bilder`."
            )

        antwort = self.client.post(
            f"https://api.cloudflare.com/client/v4/accounts/{self.konto}/ai/run/{self.modell}",
            json={"prompt": prompt[:2000], "seed": random.randint(1, 2_000_000_000)},
        )
        if antwort.status_code >= 400:
            raise _cloudflare_fehler(antwort)

        daten = antwort.json() or {}
        roh = (daten.get("result") or {}).get("image")
        if not roh:
            raise Bildfehler(f"Cloudflare lieferte kein Bild: {str(daten)[:200]}")

        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(base64.b64decode(roh))
        log.info("Bild von Cloudflare: %s", ziel)
        return ziel


def _cloudflare_fehler(antwort: httpx.Response) -> Bildfehler:
    if antwort.status_code in (401, 403):
        return Bildfehler(
            "Cloudflare weist den Zugang zurück. Der Schlüssel braucht das Recht "
            "'Workers AI' und muss zur Kontonummer passen."
        )
    if antwort.status_code == 429:
        return Bildfehler(
            "Das Tageskontingent bei Cloudflare ist aufgebraucht. Es setzt sich "
            "um Mitternacht UTC zurück."
        )
    try:
        meldung = (antwort.json().get("errors") or [{}])[0].get("message", "")
    except Exception:  # noqa: BLE001 - die Fehlermeldung darf nie selbst scheitern
        meldung = antwort.text[:160]
    return Bildfehler(f"Cloudflare antwortete mit {antwort.status_code}: {meldung}")


ANBIETER: dict[str, type] = {
    "gemini": GeminiGenerator,
    "replicate": ReplicateGenerator,
    "lokal": LokalerGenerator,
    "leonardo": LeonardoGenerator,
    "pollinations": PollinationsGenerator,
    "cloudflare": CloudflareGenerator,
}

# Der lokale Weg braucht keinen Schlüssel, sondern eine Adresse.
# Pollinations braucht nicht einmal ein Konto.
OHNE_SCHLUESSEL = {"lokal", "pollinations"}


def baue_generator(
    anbieter: str, token: str | None, modell: str, *, art: str = ""
) -> Bildgenerator | None:
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
        return klasse(token or "http://127.0.0.1:7860", modell, art=art)
    if not token:
        return None
    return klasse(token, modell)
