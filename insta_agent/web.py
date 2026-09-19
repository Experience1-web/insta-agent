"""Eine kleine Oberfläche für den Browser.

Bewusst nur mit Bordmitteln gebaut - kein Flask, kein FastAPI. Wer den
Agenten benutzt, soll nicht erst eine Paketinstallation überstehen müssen.

Der Server lauscht ausschließlich auf 127.0.0.1. Wer die Seite öffnen kann,
kann Zyklen starten und damit Geld ausgeben; das gehört nicht ins Netz.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import Settings
from .runner import Agent

log = logging.getLogger(__name__)


class LaufProtokoll(logging.Handler):
    """Sammelt die Meldungen des laufenden Zyklus für die Anzeige."""

    def __init__(self, maxlen: int = 300) -> None:
        super().__init__()
        self.zeilen: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        zeit = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        self.zeilen.append(f"{zeit}  {record.getMessage()}")


class Steuerung:
    """Hält den Zustand eines laufenden Zyklus.

    Ein Zyklus dauert Minuten. Er läuft deshalb in einem eigenen Thread,
    und die Seite fragt den Fortschritt regelmäßig ab.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.protokoll = LaufProtokoll()
        self.letzter_bericht: dict[str, Any] | None = None
        self.letzter_fehler: str | None = None

    @property
    def laeuft(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def starte(self, *, zyklen: int, hinweis: str | None) -> tuple[bool, str]:
        """Startet einen Lauf und nennt bei Ablehnung den Grund."""
        with self._lock:
            if self.laeuft:
                return False, "Es läuft bereits ein Zyklus."
            if not self.settings.anthropic_api_key:
                # Ohne Schlüssel scheitert der Agent erst tief drin mit einer
                # englischen Meldung aus dem SDK. Lieber hier abfangen.
                return False, (
                    "Kein API-Schlüssel hinterlegt. Trag ihn im Terminal ein mit: "
                    "py -m insta_agent.cli setup"
                )
            self.protokoll.zeilen.clear()
            self.letzter_fehler = None
            self.letzter_bericht = None
            self._thread = threading.Thread(
                target=self._arbeite, args=(zyklen, hinweis), daemon=True
            )
            self._thread.start()
            return True, ""

    def _arbeite(self, zyklen: int, hinweis: str | None) -> None:
        wurzel = logging.getLogger("insta_agent")
        wurzel.addHandler(self.protokoll)
        agent = Agent(self.settings)
        try:
            for nummer in range(zyklen):
                self.protokoll.zeilen.append(f"— Zyklus {nummer + 1} von {zyklen} —")
                bericht = agent.run_cycle(operator_hint=hinweis)
                self.letzter_bericht = bericht.model_dump(mode="json")
                for schritt in bericht.steps:
                    self.protokoll.zeilen.append(f"  · {schritt}")
                if bericht.halted_reason:
                    self.letzter_fehler = bericht.halted_reason
                    break
        except Exception as exc:  # noqa: BLE001 - die Seite soll den Grund zeigen
            self.letzter_fehler = _verstaendlich(exc)
            log.exception("Zyklus abgebrochen")
        finally:
            agent.close()
            wurzel.removeHandler(self.protokoll)

    # -- Daten für die Anzeige --------------------------------------------

    def zustand(self) -> dict[str, Any]:
        agent = Agent(self.settings)
        try:
            kasse = agent.treasury.state()
            identitaet = agent.identity
            strategie = agent.strategy
            plan = agent.monetization

            entwuerfe = []
            for zeile in agent.store.recent_posts(limit=12):
                daten = json.loads(zeile["draft_json"])
                entwuerfe.append(
                    {
                        "id": zeile["id"],
                        "saeule": zeile["pillar"],
                        "status": zeile["status"],
                        "caption": daten["caption"],
                        "hashtags": daten["hashtags"],
                        "bild": Path(zeile["image_path"]).name if zeile["image_path"] else None,
                        "zeitpunkt": daten.get("best_time_hint", ""),
                    }
                )

            return {
                "laeuft": self.laeuft,
                "protokoll": list(self.protokoll.zeilen),
                "fehler": self.letzter_fehler,
                "bericht": self.letzter_bericht,
                "kasse": {
                    "einlage": kasse.seed_usd,
                    "verdient": kasse.earned_usd,
                    "ausgegeben": kasse.spent_usd,
                    "kontostand": kasse.balance_usd,
                    "modus": kasse.mode.value,
                    "deckung": kasse.cost_coverage,
                    "traegt_sich": kasse.self_sustaining,
                },
                "identitaet": identitaet.model_dump(mode="json") if identitaet else None,
                "strategie": strategie.model_dump(mode="json") if strategie else None,
                "plan": plan.model_dump(mode="json") if plan else None,
                "entwuerfe": entwuerfe,
                "schluessel_da": bool(self.settings.anthropic_api_key),
                "instagram_da": self.settings.instagram_ready,
            }
        finally:
            agent.close()


def _verstaendlich(exc: Exception) -> str:
    """Macht aus einer unerwarteten Ausnahme einen brauchbaren Satz.

    Die Meldungen der Bibliotheken sind englisch und richten sich an
    Entwickler. Auf der Seite steht sonst etwas, mit dem niemand etwas
    anfangen kann.
    """
    text = str(exc)
    if "authentication" in text.lower() or "api_key" in text.lower():
        return (
            "Der API-Schlüssel fehlt oder wird nicht gefunden. Trag ihn im "
            "Terminal ein mit: py -m insta_agent.cli setup"
        )
    return f"Unerwarteter Fehler ({type(exc).__name__}): {text}"


def _handler_klasse(steuerung: Steuerung):
    seite = (Path(__file__).parent / "web_page.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = "insta-agent"

        def log_message(self, *args: Any) -> None:
            """Jede Anfrage zu protokollieren macht die Konsole unlesbar."""

        def _sende(self, status: int, typ: str, koerper: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(koerper)))
            self.end_headers()
            self.wfile.write(koerper)

        def _json(self, daten: Any, status: int = 200) -> None:
            self._sende(
                status,
                "application/json; charset=utf-8",
                json.dumps(daten, ensure_ascii=False, default=str).encode("utf-8"),
            )

        def do_GET(self) -> None:  # noqa: N802 - von BaseHTTPRequestHandler vorgegeben
            pfad = urlparse(self.path)

            if pfad.path == "/":
                self._sende(200, "text/html; charset=utf-8", seite.encode("utf-8"))
            elif pfad.path == "/api/zustand":
                self._json(steuerung.zustand())
            elif pfad.path == "/media":
                self._sende_bild(parse_qs(pfad.query).get("name", [""])[0])
            else:
                self._sende(404, "text/plain; charset=utf-8", b"Nicht gefunden")

        def _sende_bild(self, name: str) -> None:
            """Liefert ein Bild aus dem Medienordner.

            Der Dateiname wird auf seinen reinen Namen reduziert, damit
            niemand über die Adresszeile an Dateien ausserhalb des Ordners
            kommt - etwa an die .env mit dem Schlüssel.
            """
            sicher = Path(name).name
            datei = (steuerung.settings.media_dir / sicher).resolve()
            wurzel = steuerung.settings.media_dir.resolve()

            if not sicher or wurzel not in datei.parents or not datei.is_file():
                self._sende(404, "text/plain; charset=utf-8", b"Kein Bild")
                return

            typ = mimetypes.guess_type(datei.name)[0] or "application/octet-stream"
            self._sende(200, typ, datei.read_bytes())

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/start":
                self._sende(404, "text/plain; charset=utf-8", b"Nicht gefunden")
                return

            laenge = int(self.headers.get("Content-Length", 0))
            rumpf = json.loads(self.rfile.read(laenge) or b"{}")

            zyklen = max(1, min(int(rumpf.get("zyklen", 1)), 20))
            hinweis = (rumpf.get("hinweis") or "").strip() or None

            gestartet, grund = steuerung.starte(zyklen=zyklen, hinweis=hinweis)
            if gestartet:
                self._json({"gestartet": True})
            else:
                self._json({"gestartet": False, "grund": grund}, 409)

    return Handler


def starte_server(settings: Settings, port: int = 8765, oeffnen: bool = True) -> None:
    steuerung = Steuerung(settings)
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler_klasse(steuerung))
    adresse = f"http://127.0.0.1:{port}"

    if oeffnen:
        threading.Timer(0.5, lambda: webbrowser.open(adresse)).start()

    print(f"\n  Die Oberfläche läuft unter {adresse}")
    print("  Zum Beenden: Strg+C\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Beendet.")
    finally:
        server.server_close()
