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
from .mannschaft import aufstellung
from .runner import Agent

log = logging.getLogger(__name__)


def _waehlbare_modelle() -> list[str]:
    """Welche Modelle sich einstellen lassen.

    Nur solche, für die ein Preis hinterlegt ist. Ein Modell ohne Preis
    wuerde zu teuer geschaetzt und die Kasse verzerren.
    """
    from .economy.pricing import PRICING

    return sorted(PRICING)


WAEHLBARE_MODELLE = _waehlbare_modelle()

# Die Server-Kennung, an der sich ein laufendes Dashboard erkennen lässt.
KENNUNG = "insta-agent"


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

    def jetzt_veroeffentlichen(self) -> None:
        """Schickt freigegebene Beiträge sofort raus, ohne Denkzyklus."""
        agent = Agent(self.settings)
        try:
            bericht = agent.veroeffentliche_jetzt()
            for schritt in bericht.steps:
                log.info("%s", schritt)
        except Exception as exc:  # noqa: BLE001 - darf den Server nie mitreißen
            log.exception("Veröffentlichen fehlgeschlagen")
            self.letzter_fehler = _verstaendlich(exc)
        finally:
            agent.close()

    # -- Daten für die Anzeige --------------------------------------------

    def zustand(self) -> dict[str, Any]:
        agent = Agent(self.settings)
        try:
            kasse = agent.treasury.state()
            modellwahl = agent.modellwahl
            identitaet = agent.identity
            strategie = agent.strategy
            plan = agent.monetization

            farben = {"hintergrund": "#111318", "akzent": "#E4572E"}
            entwuerfe = []
            for zeile in agent.store.recent_posts(limit=12):
                daten = json.loads(zeile["draft_json"])
                if not entwuerfe and (bild := daten.get("visual")):
                    farben = {
                        "hintergrund": bild.get("background_hex", farben["hintergrund"]),
                        "akzent": bild.get("accent_hex", farben["akzent"]),
                    }
                entwuerfe.append(
                    {
                        "id": zeile["id"],
                        "saeule": zeile["pillar"],
                        "status": zeile["status"],
                        "caption": daten["caption"],
                        "hashtags": daten["hashtags"],
                        "bild": Path(zeile["image_path"]).name if zeile["image_path"] else None,
                        "zeitpunkt": daten.get("best_time_hint", ""),
                        "erwartung": daten.get("expected_outcome", ""),
                        "aufruf": daten.get("call_to_action", ""),
                        "bildtext": daten.get("hook_text_on_screen", ""),
                        "bildprompt": daten.get("image_generation_prompt", ""),
                        "erster_kommentar": daten.get("first_comment_prompt", ""),
                        # Was die Endprüfung gefunden hat. None heißt:
                        # nicht geprüft - das ist etwas anderes als sauber.
                        "pruefung": (
                            json.loads(zeile["pruefung_json"])
                            if zeile["pruefung_json"]
                            else None
                        ),
                        # Was die Bildsprache vor dem Malen gesagt hat.
                        "gestaltung": (
                            json.loads(zeile["gestaltung_json"])
                            if zeile["gestaltung_json"]
                            else None
                        ),
                    }
                )

            verlauf = [
                {
                    "zeit": z["occurred_at"][11:16],
                    "datum": z["occurred_at"][:10],
                    "art": z["kind"],
                    "text": z["message"],
                }
                for z in agent.store.recent_journal(25)
            ]
            bewertung = agent.assessment

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
                "mannschaft": aufstellung(identitaet, self.settings, modellwahl),
                "modelle": WAEHLBARE_MODELLE,
                "strategie": strategie.model_dump(mode="json") if strategie else None,
                "plan": plan.model_dump(mode="json") if plan else None,
                "entwuerfe": entwuerfe,
                "farben": farben,
                "verlauf": verlauf,
                "bewertung": bewertung.model_dump(mode="json") if bewertung else None,
                "handy_url": self.handy_url,
                "version": version(),
                "grenze_pro_zyklus": self.settings.economy.max_cost_per_cycle_usd,
                "schluessel_da": bool(self.settings.anthropic_api_key),
                "instagram_da": self.settings.instagram_ready,
                # Ob ein freigegebener Beitrag auch wirklich rausgehen kann.
                "kann_posten": self.settings.postet_wirklich,
                "eingerichtet": self.settings.can_publish,
                "malt_selbst": self.settings.bild.aktiv,
                "bildkosten": self.settings.bild.kosten_pro_bild_usd,
                "freigabe_noetig": self.settings.posting.freigabe_noetig,
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


def ist_unser_dashboard(port: int) -> bool:
    """Fragt den Port, ob dort wirklich unser Dashboard antwortet.

    Ohne diese Prüfung würde beim Aufräumen irgendein fremdes Programm
    abgeschossen, das den Port zufällig belegt - im schlimmsten Fall etwas,
    an dem gerade jemand arbeitet.

    Erkannt wird an der Server-Kennung, die jede bisherige Fassung
    mitschickt. Nach einzelnen Feldern zu suchen ging schief: Ein älteres
    Dashboard kennt die neuesten nicht, galt dadurch als fremd und lief
    einfach weiter - genau der Fall, für den das Aufräumen gedacht war.
    """
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/zustand", timeout=2
        ) as antwort:
            kennung = antwort.headers.get("Server", "")
            if KENNUNG in kennung:
                return True
            daten = json.loads(antwort.read())
    except Exception:  # noqa: BLE001 - alles andere ist eben nicht unseres
        return False

    # Ersatzweise an den Feldern, die es seit der ersten Fassung gibt.
    return isinstance(daten, dict) and {"laeuft", "kasse"} <= daten.keys()


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
            elif pfad.path == "/version":
                # Bewusst reiner Text ohne Javascript: Hieran lässt sich
                # zweifelsfrei ablesen, welcher Server gerade antwortet.
                self._sende(
                    200,
                    "text/plain; charset=utf-8",
                    (
                        f"insta-agent\n"
                        f"Stand:  {version()}\n"
                        f"Port:   {self.server.server_address[1]}\n"
                        f"Grenze: {steuerung.settings.economy.max_cost_per_cycle_usd:.2f} USD pro Zyklus\n"
                    ).encode("utf-8"),
                )
            elif pfad.path in ("/avatar", "/favicon.ico"):
                # Auch als Symbol im Browsertab: Wer mehrere Fenster offen
                # hat, erkennt seinen Mitarbeiter am Gesicht.
                self._sende_avatar(parse_qs(pfad.query).get("wer", ["chef"])[0])
            elif pfad.path == "/qr":
                self._sende_qr()
            elif pfad.path == "/media":
                self._sende_bild(parse_qs(pfad.query).get("name", [""])[0])
            else:
                self._sende(404, "text/plain; charset=utf-8", b"Nicht gefunden")

        def _entscheide(self, rumpf: dict) -> None:
            """Freigeben oder verwerfen - das Ja des Betreibers zu einem Entwurf.

            Nur ein freigegebener Entwurf geht bei Jonas' nächstem Zyklus
            nach draußen. Ohne diesen Knopf passiert nichts.
            """
            if steuerung.nur_lesen:
                self._json({"ok": False, "grund": "Diese Ansicht ist nur zum Nachsehen."}, 409)
                return

            try:
                post_id = int(rumpf.get("id"))
            except (TypeError, ValueError):
                self._json({"ok": False, "grund": "Kein gültiger Beitrag."}, 400)
                return

            wahl = str(rumpf.get("wahl") or "")
            if wahl not in ("freigeben", "verwerfen"):
                self._json({"ok": False, "grund": "Unbekannte Entscheidung."}, 400)
                return

            agent = Agent(steuerung.settings)
            try:
                if wahl == "freigeben":
                    geaendert = agent.store.freigeben(post_id)
                    text = f"Beitrag {post_id} freigegeben"
                else:
                    geaendert = agent.store.verwerfen(post_id)
                    text = f"Beitrag {post_id} verworfen"

                if not geaendert:
                    self._json(
                        {"ok": False, "grund": "Der Beitrag ist dafür nicht mehr offen."}, 409
                    )
                    return
                agent.store.log("decision", text)
            finally:
                agent.close()

            # Das Ja des Betreibers ist der Auslöser, nicht der nächste
            # Zyklus. Veröffentlichen kostet kein Guthaben - darauf zu
            # warten wäre nur Wartezeit ohne Gegenwert.
            if wahl == "freigeben" and steuerung.settings.postet_wirklich:
                threading.Thread(target=steuerung.jetzt_veroeffentlichen, daemon=True).start()
                self._json({"ok": True, "geht_raus": True})
                return

            self._json({"ok": True, "geht_raus": False})

        def _buche_einnahme(self, rumpf: dict) -> None:
            """Trägt eine Einnahme in die Kasse des Agenten ein.

            Geld empfangen kann nur ein Mensch. Erst wenn er es hier
            einträgt, sieht der Agent, dass er seine Kosten deckt.
            """
            if steuerung.nur_lesen:
                self._json({"ok": False, "grund": "Diese Ansicht ist nur zum Nachsehen."}, 409)
                return
            try:
                betrag = float(rumpf.get("betrag", 0))
            except (TypeError, ValueError):
                betrag = 0.0
            if betrag <= 0:
                self._json({"ok": False, "grund": "Der Betrag muss größer als null sein."}, 400)
                return

            agent = Agent(steuerung.settings)
            try:
                agent.treasury.earn(
                    betrag,
                    str(rumpf.get("kategorie") or "other"),
                    str(rumpf.get("notiz") or ""),
                )
                agent.store.log("revenue", f"Einnahme {betrag:.2f} USD über die Oberfläche")
            finally:
                agent.close()
            self._json({"ok": True})

        def _setze_kasse(self, rumpf: dict) -> None:
            """Trägt den echten Kontostand ein.

            Der Agent schätzt seine Kosten aus Tokenzahl und Preisliste.
            Was auf der Abrechnungsseite steht, ist die Wahrheit - und
            daran hängen Sparbetrieb und Stopp. Nach jedem Aufladen gehört
            die neue Zahl hier hinein.
            """
            if steuerung.nur_lesen:
                self._json({"ok": False, "grund": "Diese Ansicht ist nur zum Nachsehen."}, 409)
                return
            try:
                guthaben = float(rumpf.get("guthaben"))
            except (TypeError, ValueError):
                self._json({"ok": False, "grund": "Das ist keine Zahl."}, 400)
                return
            if guthaben < 0:
                self._json({"ok": False, "grund": "Ein Guthaben ist nicht negativ."}, 400)
                return

            agent = Agent(steuerung.settings)
            try:
                bereits = _bereits_heute(agent)
                agent.treasury.setze_anker(guthaben, bereits)
                stand = agent.treasury.state()
                agent.store.log(
                    "treasury",
                    f"Kontostand auf {guthaben:.2f} USD gesetzt"
                    + (" - rechnet ab jetzt selbst nach" if bereits is not None else ""),
                )
            finally:
                agent.close()
            self._json(
                {"ok": True, "stand": round(stand.balance_usd, 2), "modus": stand.mode.value}
            )

        def _setze_modell(self, rumpf: dict) -> None:
            """Stellt um, mit welchem Modell eine Rolle arbeitet.

            Welches Modell eine Rolle braucht, hängt davon ab, wie gut die
            Ergebnisse sind und wie viel Geld da ist. Das gehört dem
            Betreiber in die Hand - ohne Neustart und ohne Datei.
            """
            from .mannschaft import KEY_MODELLWAHL, NACH_SCHLUESSEL

            if steuerung.nur_lesen:
                self._json({"ok": False, "grund": "Diese Ansicht ist nur zum Nachsehen."}, 409)
                return

            wer = str(rumpf.get("wer") or "")
            if wer not in NACH_SCHLUESSEL:
                self._json({"ok": False, "grund": "Diese Rolle gibt es nicht."}, 400)
                return

            modell = str(rumpf.get("modell") or "").strip()
            # Leer heisst: zurueck auf die Voreinstellung.
            if modell and modell not in WAEHLBARE_MODELLE:
                self._json({"ok": False, "grund": "Dieses Modell kenne ich nicht."}, 400)
                return

            agent = Agent(steuerung.settings)
            try:
                wahl = dict(agent.modellwahl)
                if modell:
                    wahl[wer] = modell
                else:
                    wahl.pop(wer, None)
                agent.store.set_json(KEY_MODELLWAHL, wahl)
                agent.store.log(
                    "modell",
                    f"{NACH_SCHLUESSEL[wer].rolle} arbeitet jetzt mit "
                    + (modell or "der Voreinstellung"),
                )
            finally:
                agent.close()
            self._json({"ok": True})

        def _male_portraits(self) -> None:
            """Lässt Porträts für die Mannschaft malen.

            Kostet echtes Geld beim Bilddienst, deshalb nur auf Knopfdruck
            und nie im Zyklus. Wer schon ein Bild hat, bekommt kein neues.
            """
            from .imaging.generator import baue_generator
            from .imaging.portraits import male_portrait, portraitpfad
            from .mannschaft import ROLLEN

            if steuerung.nur_lesen:
                self._json({"ok": False, "grund": "Diese Ansicht ist nur zum Nachsehen."}, 409)
                return

            einst = steuerung.settings
            generator = baue_generator(einst.bild.anbieter, einst.bild.token, einst.bild.modell)
            if generator is None:
                self._json(
                    {
                        "ok": False,
                        "grund": "Kein Bilddienst eingerichtet. Im Terminal: insta-agent bilder",
                    },
                    409,
                )
                return

            agent = Agent(einst)
            try:
                identitaet = agent.identity
                gemalt: list[str] = []
                gruende: list[str] = []
                for rolle in ROLLEN:
                    if rolle.schluessel == "chef" and identitaet is None:
                        continue
                    ziel = portraitpfad(einst.media_dir, rolle.schluessel)
                    if ziel.is_file():
                        continue
                    pfad, grund = male_portrait(generator, rolle, ziel, identitaet)
                    if pfad:
                        gemalt.append(rolle.schluessel)
                    else:
                        # Der echte Grund, nicht "hat nicht geklappt". Beim
                        # ersten Fehlschlag aufhoeren: Wenn das Tageslimit
                        # erreicht ist, scheitern die naechsten genauso.
                        gruende.append(f"{rolle.name or rolle.rolle}: {grund}")
                        break
                if gemalt:
                    agent.store.log("portrait", f"{len(gemalt)} Porträt(s) gemalt")
                if gruende:
                    agent.store.log("portrait_error", gruende[0])
            finally:
                agent.close()
                if hasattr(generator, "close"):
                    generator.close()

            self._json({"ok": True, "gemalt": gemalt, "gruende": gruende})

        def _sende_avatar(self, wer: str = "chef") -> None:
            """Das Porträt einer Rolle.

            Drei Stufen, in dieser Reihenfolge: ein eigenes Bild des
            Betreibers unter assets/, ein gemaltes Porträt aus dem
            Medienordner, und zuletzt das gezeichnete Zeichen aus
            Initialen und Farben. Die letzte Stufe kann nicht fehlschlagen
            - es gibt immer etwas zu sehen.
            """
            import mimetypes as mt

            from .config import REPO_ROOT
            from .imaging.avatar import render_avatar
            from .imaging.portraits import portraitpfad
            from .mannschaft import NACH_SCHLUESSEL

            rolle = NACH_SCHLUESSEL.get(wer) or NACH_SCHLUESSEL["chef"]
            stamm = "portrait" if rolle.schluessel == "chef" else f"portrait_{rolle.schluessel}"

            for endung in ("png", "jpg", "jpeg", "webp", "gif"):
                eigenes = REPO_ROOT / "assets" / f"{stamm}.{endung}"
                if eigenes.is_file():
                    typ = mt.guess_type(eigenes.name)[0] or "image/png"
                    self._sende(200, typ, eigenes.read_bytes())
                    return

            gemalt = portraitpfad(steuerung.settings.media_dir, rolle.schluessel)
            if gemalt.is_file():
                self._sende(200, "image/png", gemalt.read_bytes())
                return

            zustand = steuerung.zustand()
            identitaet = zustand.get("identitaet")
            if rolle.schluessel == "chef" and not identitaet:
                self._sende(404, "text/plain; charset=utf-8", b"Noch kein Profil")
                return

            name = identitaet["agent_name"] if rolle.schluessel == "chef" else rolle.name
            farben = zustand.get("farben", {})
            pfad = steuerung.settings.media_dir / f"_zeichen_{rolle.schluessel}.png"
            render_avatar(
                name,
                pfad,
                background_hex=farben.get("hintergrund", "#111318"),
                accent_hex=farben.get("akzent", "#E4572E"),
            )
            self._sende(200, "image/png", pfad.read_bytes())

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
                self._json({"ok": False, "grund": "Kein Zugang."}, 403)
                return

            pfad = urlparse(self.path).path
            if pfad not in (
                "/api/start",
                "/api/einnahme",
                "/api/entscheiden",
                "/api/kasse",
                "/api/modell",
                "/api/portraits",
            ):
                self._sende(404, "text/plain; charset=utf-8", b"Nicht gefunden")
                return

            laenge = int(self.headers.get("Content-Length", 0))
            rumpf = json.loads(self.rfile.read(laenge) or b"{}")

            if pfad == "/api/einnahme":
                self._buche_einnahme(rumpf)
                return

            if pfad == "/api/entscheiden":
                self._entscheide(rumpf)
                return

            if pfad == "/api/kasse":
                self._setze_kasse(rumpf)
                return

            if pfad == "/api/modell":
                self._setze_modell(rumpf)
                return

            if pfad == "/api/portraits":
                self._male_portraits()
                return

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
    """Belegt den Wunschport - und weicht aus, wenn das nicht gelingt.

    Ein altes Dashboard wird nach Möglichkeit beendet. Gelingt das nicht,
    wird nicht aufgegeben, sondern der nächste freie Port genommen. Das
    Aufräumen scheiterte in der Praxis wiederholt aus Gründen, die sich aus
    der Ferne nicht klären ließen; ein Dashboard, das dann gar nicht
    startet, ist das schlechtestmögliche Ergebnis.
    """
    import time

    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError:
        pass

    if ist_unser_dashboard(port):
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
    else:
        print(f"\n  Port {port} ist von einem anderen Programm belegt.")

    for kandidat in range(port + 1, port + 21):
        try:
            server = ThreadingHTTPServer((host, kandidat), handler)
        except OSError:
            continue
        print(
            f"\n  Der alte Platz ließ sich nicht räumen - das Dashboard läuft\n"
            f"  deshalb auf Port {kandidat}. Nimm die Adresse von unten,\n"
            f"  nicht die aus einem alten Browser-Tab.\n"
        )
        return server

    print(f"\n  Zwischen {port} und {port + 20} ist kein Platz frei.\n")
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
    port = server.server_address[1]

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


def _bereits_heute(agent) -> float | None:
    """Was heute vor dem Eintragen schon abgerechnet wurde - None ohne Zugang.

    Die Abrechnung löst nur ganze Tage auf. Ohne diesen Wert ginge der
    heutige Verbrauch später ein zweites Mal vom Guthaben ab.
    """
    if agent.abrechnung is None:
        return None
    from datetime import datetime, timezone

    try:
        return agent.abrechnung.kosten_seit(datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - kein Grund, den Eintrag zu verlieren
        log.warning("Abrechnung nicht erreichbar: %s", exc)
        return None
