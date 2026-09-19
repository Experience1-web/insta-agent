"""Eine kleine Oberfläche für den Browser.

Bewusst nur mit Bordmitteln gebaut - kein Flask, kein FastAPI. Wer den
Agenten benutzt, soll nicht erst eine Paketinstallation überstehen müssen.

Der Server lauscht ausschließlich auf 127.0.0.1. Wer die Seite öffnen kann,
kann Zyklen starten und damit Geld ausgeben; das gehört nicht ins Netz.
"""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import secrets
import socket
import threading
import webbrowser
from collections import deque
from datetime import datetime, timedelta, timezone
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

    def __init__(
        self, settings: Settings, *, nur_lesen: bool = False, auto_stunden: float = 0
    ) -> None:
        self.settings = settings
        self.nur_lesen = nur_lesen
        self.auto_stunden = auto_stunden
        self.handy_url: str | None = None
        """Die vollständige Adresse fürs Handy, samt Zugangswort."""
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.protokoll = LaufProtokoll()
        self.letzter_bericht: dict[str, Any] | None = None
        self.letzter_fehler: str | None = None

    @property
    def laeuft(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def starte(
        self, *, zyklen: int, hinweis: str | None, von_hand: bool = True
    ) -> tuple[bool, str]:
        """Startet einen Lauf und nennt bei Ablehnung den Grund.

        von_hand unterscheidet den Knopfdruck vom Arbeitstakt. Der
        Lesemodus sperrt nur fremde Zugriffe, nicht den Agenten selbst.
        """
        with self._lock:
            if von_hand and self.nur_lesen:
                return False, (
                    "Diese Ansicht ist nur zum Nachsehen freigegeben. Starten geht "
                    "am Rechner, auf dem der Agent läuft."
                )
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

    # -- Arbeitstakt -------------------------------------------------------

    def naechster_lauf(self) -> datetime | None:
        """Wann der Agent von selbst wieder arbeitet. None heißt: gar nicht."""
        if self.auto_stunden <= 0:
            return None
        agent = Agent(self.settings)
        try:
            zuletzt = agent.store.last_cycle_at()
        finally:
            agent.close()
        if zuletzt is None:
            return datetime.now(timezone.utc)
        return zuletzt + timedelta(hours=self.auto_stunden)

    def _takt(self) -> None:
        """Weckt den Agenten, wenn seine Pause vorbei ist.

        Der Abstand zählt ab dem letzten Zyklus, nicht ab dem Start des
        Programms. Sonst würde jeder Neustart des Rechners erneut Geld
        kosten - bei jemandem, der seinen Laptop mehrmals täglich
        hochfährt, wäre das Budget schnell weg.
        """
        while True:
            try:
                faellig = self.naechster_lauf()
                if faellig and datetime.now(timezone.utc) >= faellig and not self.laeuft:
                    log.info("Arbeitstakt: der Agent legt los")
                    self.starte(zyklen=1, hinweis=None, von_hand=False)
            except Exception:  # noqa: BLE001 - der Takt darf nie ganz abreißen
                log.exception("Arbeitstakt gestolpert")
            threading.Event().wait(300)

    def starte_takt(self) -> None:
        if self.auto_stunden > 0:
            threading.Thread(target=self._takt, daemon=True).start()

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
                "nur_lesen": self.nur_lesen,
                "auto_stunden": self.auto_stunden,
                "naechster_lauf": (n.isoformat() if (n := self.naechster_lauf()) else None),
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
                "handy_url": self.handy_url,
                "version": version(),
                "grenze_pro_zyklus": self.settings.economy.max_cost_per_cycle_usd,
                "schluessel_da": bool(self.settings.anthropic_api_key),
                "instagram_da": self.settings.instagram_ready,
            }
        finally:
            agent.close()


def pids_auf_port(netstat_ausgabe: str, port: int) -> set[str]:
    """Liest aus der netstat-Ausgabe, welcher Prozess den Port hält.

    Bewusst ohne das Wort "LISTENING": Ein deutsches Windows schreibt dort
    "ABHÖREN", ein französisches wieder etwas anderes. Stattdessen wird
    die lokale Adresse geprüft - die sieht überall gleich aus.
    """
    gefunden: set[str] = set()
    for zeile in netstat_ausgabe.splitlines():
        teile = zeile.split()
        if len(teile) < 4 or teile[0].upper() != "TCP":
            continue
        lokal = teile[1]
        if not lokal.rsplit(":", 1)[-1] == str(port):
            continue
        pid = teile[-1]
        # 0 und 4 gehören dem System und werden nie beendet.
        if pid.isdigit() and pid not in ("0", "4"):
            gefunden.add(pid)
    return gefunden


def beende_dashboard(port: int) -> tuple[bool, str]:
    """Beendet den Prozess, der den Port belegt.

    Unter Windows über netstat und taskkill, sonst über lsof - beides
    gehört zum System, es braucht kein Zusatzwerkzeug.
    """
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            netstat = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True,
                text=True,
                timeout=10,
                errors="replace",
            )
            pids = pids_auf_port(netstat.stdout, port)
            for pid in pids:
                subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10)
        else:
            lsof = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True, timeout=10
            )
            pids = {p for p in lsof.stdout.split() if p}
            for pid in pids:
                subprocess.run(["kill", "-9", pid], capture_output=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return False, f"Konnte das Dashboard nicht beenden: {exc}"

    if not pids:
        return False, f"Kein Prozess gefunden, der Port {port} belegt."
    return True, f"Dashboard beendet ({len(pids)} Prozess(e) auf Port {port})."


def version() -> str:
    """Welcher Stand gerade läuft.

    Ohne diese Angabe lässt sich nicht erkennen, ob ein `git pull`
    angekommen ist - man sieht nur, dass sich das Verhalten nicht
    geändert hat, und sucht den Fehler an der falschen Stelle.
    """
    import subprocess

    from .config import REPO_ROOT

    try:
        ergebnis = subprocess.run(
            ["git", "log", "-1", "--format=%h vom %cd", "--date=format:%d.%m. %H:%M"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return ergebnis.stdout.strip() or "unbekannt"
    except Exception:  # noqa: BLE001 - ohne git ist das kein Grund zu scheitern
        return "unbekannt"


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


def _handler_klasse(steuerung: Steuerung, token: str | None):
    seiten_datei = Path(__file__).parent / "web_page.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "insta-agent"

        def _zugang_erlaubt(self) -> bool:
            """Vom eigenen Rechner ohne Zugangswort, von außen nur damit.

            Wer die Seite erreicht, kann Geld ausgeben - deshalb reicht
            "steht halt im eigenen WLAN" als Schutz nicht.
            """
            if self.client_address[0] in ("127.0.0.1", "::1"):
                return True
            if not token:
                return False
            mitgeliefert = self.headers.get("X-Token") or parse_qs(
                urlparse(self.path).query
            ).get("token", [""])[0]
            return hmac.compare_digest(mitgeliefert, token)

        def log_message(self, *args: Any) -> None:
            """Jede Anfrage zu protokollieren macht die Konsole unlesbar."""

        def _sende(self, status: int, typ: str, koerper: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(koerper)))
            # Ohne diesen Hinweis zeigt der Browser nach einer
            # Aktualisierung weiter die alte Seite aus seinem Speicher.
            self.send_header("Cache-Control", "no-store, must-revalidate")
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

            if not self._zugang_erlaubt():
                self._sende(
                    403,
                    "text/html; charset=utf-8",
                    "<h1>Kein Zugang</h1><p>Ruf die Seite mit dem Zugangswort auf, "
                    "das beim Start angezeigt wurde.</p>".encode("utf-8"),
                )
                return

            if pfad.path == "/":
                # Bei jedem Aufruf frisch lesen: nach einem `git pull` wirkt
                # eine geänderte Seite sofort, ohne den Server neu zu starten.
                self._sende(
                    200,
                    "text/html; charset=utf-8",
                    seiten_datei.read_text(encoding="utf-8").encode("utf-8"),
                )
            elif pfad.path == "/api/zustand":
                self._json(steuerung.zustand())
            elif pfad.path == "/qr":
                self._sende_qr()
            elif pfad.path == "/media":
                self._sende_bild(parse_qs(pfad.query).get("name", [""])[0])
            else:
                self._sende(404, "text/plain; charset=utf-8", b"Nicht gefunden")

        def _sende_qr(self) -> None:
            """Die Handy-Adresse als QR-Code, damit niemand sie abtippen muss."""
            if not steuerung.handy_url:
                self._sende(404, "text/plain; charset=utf-8", b"Keine Freigabe aktiv")
                return

            import io

            import segno

            puffer = io.BytesIO()
            segno.make(steuerung.handy_url, error="m").save(
                puffer, kind="png", scale=6, border=2, dark="#111318", light="#ffffff"
            )
            self._sende(200, "image/png", puffer.getvalue())

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
            if not self._zugang_erlaubt():
                self._json({"gestartet": False, "grund": "Kein Zugang."}, 403)
                return
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


def eigene_ip() -> str:
    """Die Adresse, unter der andere Geräte im Netz den Rechner erreichen."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Es wird nichts gesendet; der Aufruf verrät nur die Route.
            s.connect(("192.0.2.1", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _binde_port(host: str, port: int, handler) -> ThreadingHTTPServer:
    """Belegt den Port und räumt dafür nötigenfalls ein altes Dashboard weg.

    Ein noch laufendes altes Dashboard war der häufigste Stolperstein: Das
    neue startete nicht, der Browser zeigte weiter den alten Stand, und von
    außen sah es aus, als käme eine Aktualisierung nicht an. Das hier
    aufzuräumen gehört nach Python - in einer Batch-Datei lässt es sich
    nicht prüfen.
    """
    import time

    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError:
        pass

    print(f"\n  Port {port} war belegt - beende das alte Dashboard …")
    beendet, meldung = beende_dashboard(port)
    print(f"  {meldung}")

    if beendet:
        # Das Betriebssystem braucht einen Moment, bis der Port frei ist.
        for _ in range(20):
            time.sleep(0.25)
            try:
                return ThreadingHTTPServer((host, port), handler)
            except OSError:
                continue

    print(
        f"\n  Der Port {port} lässt sich nicht belegen.\n"
        f"  Schließ alle schwarzen Fenster dieses Programms und versuch es erneut.\n"
    )
    raise SystemExit(1)


def starte_server(
    settings: Settings,
    port: int = 8765,
    oeffnen: bool = True,
    host: str = "127.0.0.1",
    nur_lesen: bool = False,
    auto_stunden: float = 0,
) -> None:
    nach_aussen = host not in ("127.0.0.1", "localhost", "::1")

    token = settings.web_token
    if nach_aussen and not token:
        # Ohne Zugangswort wäre die Seite für jeden im Netz bedienbar.
        from .config import set_env_value

        token = secrets.token_urlsafe(12)
        set_env_value("WEB_TOKEN", token)

    steuerung = Steuerung(settings, nur_lesen=nur_lesen, auto_stunden=auto_stunden)
    steuerung.starte_takt()

    server = _binde_port(host, port, _handler_klasse(steuerung, token))

    if nach_aussen:
        steuerung.handy_url = f"http://{eigene_ip()}:{port}/?token={token}"

    lokal = f"http://127.0.0.1:{port}"
    if oeffnen:
        threading.Timer(0.5, lambda: webbrowser.open(lokal)).start()

    print(f"\n  Auf diesem Rechner:  {lokal}")
    if nach_aussen and steuerung.handy_url:
        print(f"  Von anderen Geräten: {steuerung.handy_url}")
        print("\n  Diese Adresse enthält dein Zugangswort - behandle sie wie ein Passwort.")
        if nur_lesen:
            print("  Nur-Lesen-Modus: von außen kann niemand einen Zyklus starten.")

        print("\n  Oder scann das hier mit der Handykamera:\n")
        try:
            import segno

            segno.make(steuerung.handy_url, error="m").terminal(compact=True)
        except Exception:  # noqa: BLE001 - ohne QR bleibt die Adresse zum Abtippen
            print("  (QR-Code nicht darstellbar - nimm die Adresse von oben.)")
        print(f"\n  Der Code steht auch im Dashboard unter {lokal}")
    if auto_stunden > 0:
        print(f"\n  Arbeitstakt: alle {auto_stunden:g} Stunden von selbst.")
    print("\n  Zum Beenden: Strg+C\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Beendet.")
    finally:
        server.server_close()
