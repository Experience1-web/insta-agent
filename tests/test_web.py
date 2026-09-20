"""Die Oberfläche darf keine Datei ausliefern, die ihr nicht gehört."""

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from insta_agent.config import EconomyConfig, LLMConfig, PostingConfig, Settings
from insta_agent.web import Steuerung, _verstaendlich


@pytest.fixture
def settings(tmp_path):
    return Settings(
        llm=LLMConfig(),
        economy=EconomyConfig(treasury_start_usd=5.0),
        posting=PostingConfig(),
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )


def test_ohne_schluessel_startet_kein_lauf(settings):
    """Sonst scheitert es erst tief im SDK mit einer englischen Meldung."""
    settings.anthropic_api_key = None
    steuerung = Steuerung(settings)

    gestartet, grund = steuerung.starte(zyklen=1, hinweis=None)
    assert not gestartet
    assert "setup" in grund
    assert not steuerung.laeuft


def test_zustand_laesst_sich_ohne_jeden_zyklus_abrufen(settings):
    """Die Seite muss auch beim allerersten Aufruf etwas anzeigen können."""
    zustand = Steuerung(settings).zustand()

    assert zustand["laeuft"] is False
    assert zustand["identitaet"] is None
    assert zustand["entwuerfe"] == []
    assert zustand["kasse"]["einlage"] == 5.0
    # Muss sich für die Antwort in JSON verwandeln lassen.
    json.dumps(zustand, default=str)


def test_authentifizierungsfehler_wird_uebersetzt():
    text = _verstaendlich(TypeError("Could not resolve authentication method"))
    assert "Schlüssel" in text
    assert "insta_agent.cli setup" in text


def test_unbekannter_fehler_behaelt_seinen_typ():
    text = _verstaendlich(ValueError("etwas ganz anderes"))
    assert "ValueError" in text
    assert "etwas ganz anderes" in text


# --- Zugang von außen -----------------------------------------------------


class FakeHeaders(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


def _handler(token, *, von, pfad="/api/zustand"):
    """Baut einen Handler nach, ohne einen echten Server zu starten."""
    from insta_agent.web import Steuerung, _handler_klasse
    from insta_agent.config import Settings

    klasse = _handler_klasse(Steuerung(Settings()), token)
    h = object.__new__(klasse)
    h.client_address = (von, 12345)
    h.path = pfad
    h.headers = FakeHeaders()
    return h


def test_vom_eigenen_rechner_ohne_zugangswort(tmp_path):
    assert _handler("geheim", von="127.0.0.1")._zugang_erlaubt()


def test_von_aussen_ohne_zugangswort_abgelehnt():
    """Sonst könnte jeder im WLAN Zyklen starten und Guthaben verbrauchen."""
    assert not _handler("geheim", von="192.168.1.50")._zugang_erlaubt()


def test_von_aussen_mit_falschem_zugangswort_abgelehnt():
    h = _handler("geheim", von="192.168.1.50", pfad="/api/zustand?token=geraten")
    assert not h._zugang_erlaubt()


def test_von_aussen_mit_richtigem_zugangswort_erlaubt():
    h = _handler("geheim", von="192.168.1.50", pfad="/api/zustand?token=geheim")
    assert h._zugang_erlaubt()


def test_zugangswort_auch_als_kopfzeile():
    h = _handler("geheim", von="192.168.1.50")
    h.headers = FakeHeaders({"X-Token": "geheim"})
    assert h._zugang_erlaubt()


def test_ohne_gesetztes_zugangswort_kommt_von_aussen_niemand_rein():
    """Ein fehlendes Zugangswort darf nicht als 'alles erlaubt' gelten."""
    assert not _handler(None, von="192.168.1.50")._zugang_erlaubt()
    h = _handler(None, von="192.168.1.50", pfad="/api/zustand?token=")
    assert not h._zugang_erlaubt()


def test_nur_lesen_verweigert_den_start(settings):
    settings.anthropic_api_key = "sk-ant-test"
    steuerung = Steuerung(settings, nur_lesen=True)

    gestartet, grund = steuerung.starte(zyklen=1, hinweis=None)
    assert not gestartet
    assert "nachsehen" in grund.lower()
    assert steuerung.zustand()["nur_lesen"] is True


# --- Arbeitstakt ----------------------------------------------------------


def test_ohne_takt_arbeitet_er_nie_von_selbst(settings):
    assert Steuerung(settings, auto_stunden=0).naechster_lauf() is None


def test_ohne_bisherigen_zyklus_legt_er_sofort_los(settings):
    """Beim allerersten Start soll er nicht erst 24 Stunden warten."""
    from datetime import datetime, timezone

    faellig = Steuerung(settings, auto_stunden=24).naechster_lauf()
    assert faellig is not None
    assert faellig <= datetime.now(timezone.utc)


def test_neustart_kurz_nach_einem_zyklus_kostet_nichts(settings):
    """Der Kern der Sache.

    Wer seinen Laptop mehrmals am Tag hochfährt, darf nicht jedes Mal
    einen bezahlten Zyklus auslösen. Der Abstand zählt ab dem letzten
    Zyklus, nicht ab dem Programmstart.
    """
    from datetime import datetime, timedelta, timezone

    from insta_agent.store import Store

    speicher = Store(settings.db_path)
    speicher.log("cycle", "gerade eben fertig", 1)
    speicher.close()

    # Frisch gestartete Steuerung, als wäre der Rechner neu hochgefahren.
    faellig = Steuerung(settings, auto_stunden=24).naechster_lauf()
    jetzt = datetime.now(timezone.utc)

    assert faellig > jetzt
    assert faellig - jetzt > timedelta(hours=23)


def test_nach_abgelaufener_pause_ist_er_wieder_dran(settings):
    from datetime import datetime, timedelta, timezone

    from insta_agent.store import Store

    speicher = Store(settings.db_path)
    vorgestern = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    speicher._conn.execute(
        "INSERT INTO journal(occurred_at, cycle, kind, message) VALUES(?,?,?,?)",
        (vorgestern, 1, "cycle", "lange her"),
    )
    speicher._conn.commit()
    speicher.close()

    assert Steuerung(settings, auto_stunden=24).naechster_lauf() < datetime.now(timezone.utc)


def test_der_takt_darf_trotz_lesemodus_arbeiten(settings):
    """Der Lesemodus sperrt fremde Zugriffe, nicht den Agenten selbst."""
    settings.anthropic_api_key = None  # nur der Lesemodus soll hier prüfen
    steuerung = Steuerung(settings, nur_lesen=True, auto_stunden=24)

    von_hand, grund_hand = steuerung.starte(zyklen=1, hinweis=None, von_hand=True)
    assert not von_hand and "nachsehen" in grund_hand.lower()

    # Der Takt scheitert erst am fehlenden Schlüssel, nicht am Lesemodus.
    _, grund_takt = steuerung.starte(zyklen=1, hinweis=None, von_hand=False)
    assert "nachsehen" not in grund_takt.lower()
    assert "Schlüssel" in grund_takt


# --- QR-Code fürs Handy ---------------------------------------------------


def test_ohne_freigabe_gibt_es_keine_handy_adresse(settings):
    assert Steuerung(settings).zustand()["handy_url"] is None


def test_der_qr_code_enthaelt_die_volle_adresse():
    """Sonst nützt das Scannen nichts - das Zugangswort muss mit drin sein."""
    import io

    import segno

    adresse = "http://192.168.1.42:8765/?token=geheim123"
    puffer = io.BytesIO()
    segno.make(adresse, error="m").save(puffer, kind="png", scale=4)

    assert puffer.getvalue().startswith(b"\x89PNG")
    assert segno.make(adresse, error="m").matrix is not None


def test_der_zustand_verraet_den_laufenden_stand(settings):
    """Ohne diese Angabe merkt niemand, dass ein `git pull` nicht ankam."""
    zustand = Steuerung(settings).zustand()

    assert "version" in zustand
    assert zustand["grenze_pro_zyklus"] == settings.economy.max_cost_per_cycle_usd


def test_belegter_port_fuehrt_zum_ausweichen_statt_zum_abbruch(capsys):
    """Ein belegter Port darf den Start nie verhindern.

    Das Aufräumen scheiterte in der Praxis wiederholt. Ein Dashboard, das
    dann gar nicht startet, ist das schlechteste Ergebnis - also wird
    ausgewichen. Das fremde Programm bleibt dabei unangetastet.
    """
    import socket

    from insta_agent.web import _binde_port

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]

    server = None
    try:
        server = _binde_port("127.0.0.1", port, BaseHTTPRequestHandler)
        gewaehlt = server.server_address[1]

        assert gewaehlt != port, "es wurde nicht ausgewichen"
        assert port < gewaehlt <= port + 20

        ausgabe = capsys.readouterr().out
        assert "anderen Programm belegt" in ausgabe
        assert f"Port {gewaehlt}" in ausgabe, "der neue Port wird nicht genannt"

        # Das fremde Programm läuft weiter.
        assert blocker.fileno() != -1
    finally:
        if server:
            server.server_close()
        blocker.close()


# --- Den belegenden Prozess finden ---------------------------------------

DEUTSCHE_NETSTAT = """
Aktive Verbindungen

  Proto  Lokale Adresse         Remoteadresse          Status           PID
  TCP    0.0.0.0:135            0.0.0.0:0              ABHÖREN          1128
  TCP    127.0.0.1:8765         0.0.0.0:0              ABHÖREN          9876
  TCP    127.0.0.1:8765         127.0.0.1:54321        HERGESTELLT      9876
  TCP    192.168.1.5:49711      104.18.2.1:443         HERGESTELLT      4444
"""

ENGLISCHE_NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       9876
  TCP    0.0.0.0:445            0.0.0.0:0              LISTENING       4
"""


def test_deutscher_status_wird_gefunden():
    """Genau hier scheiterte es: deutsches Windows schreibt "ABHÖREN"."""
    from insta_agent.web import pids_auf_port

    assert pids_auf_port(DEUTSCHE_NETSTAT, 8765) == {"9876"}


def test_englischer_status_ebenso():
    from insta_agent.web import pids_auf_port

    assert pids_auf_port(ENGLISCHE_NETSTAT, 8765) == {"9876"}


def test_fremde_ports_bleiben_unberuehrt():
    from insta_agent.web import pids_auf_port

    assert pids_auf_port(DEUTSCHE_NETSTAT, 443) == set()
    assert pids_auf_port(DEUTSCHE_NETSTAT, 135) == {"1128"}


def test_systemprozesse_werden_nie_beendet():
    """PID 4 gehört Windows selbst - den abzuschießen wäre fatal."""
    from insta_agent.web import pids_auf_port

    assert "4" not in pids_auf_port(ENGLISCHE_NETSTAT, 445)


def test_ein_port_der_nur_als_gegenstelle_vorkommt_zaehlt_nicht():
    from insta_agent.web import pids_auf_port

    assert pids_auf_port(DEUTSCHE_NETSTAT, 54321) == set()


def test_ein_aelteres_dashboard_wird_trotzdem_als_eigenes_erkannt():
    """Der Fehler, der das Aufräumen wirkungslos machte.

    Geprüft wurde auf ein Feld, das erst später dazukam. Ein älteres
    Dashboard galt dadurch als fremdes Programm und lief weiter - obwohl
    genau dafür aufgeräumt werden sollte.
    """
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from insta_agent.web import ist_unser_dashboard

    class AlteFassung(BaseHTTPRequestHandler):
        server_version = "insta-agent"

        def log_message(self, *args):
            pass

        def do_GET(self):
            # Bewusst ohne "version" - so sah die erste Fassung aus.
            koerper = json.dumps({"laeuft": False, "kasse": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(koerper)))
            self.end_headers()
            self.wfile.write(koerper)

    server = ThreadingHTTPServer(("127.0.0.1", 0), AlteFassung)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert ist_unser_dashboard(port)
    finally:
        server.shutdown()
        server.server_close()


def test_ein_fremder_webserver_gilt_weiterhin_als_fremd():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from insta_agent.web import ist_unser_dashboard

    class FremderDienst(BaseHTTPRequestHandler):
        server_version = "nginx"
        sys_version = ""

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"hi")

    server = ThreadingHTTPServer(("127.0.0.1", 0), FremderDienst)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert not ist_unser_dashboard(port)
    finally:
        server.shutdown()
        server.server_close()


def test_die_versionsseite_kommt_ohne_javascript_aus(settings):
    """Zur Diagnose, wenn unklar ist, welcher Server gerade antwortet.

    Reiner Text: kein Javascript, kein Zwischenspeicher, keine Zweifel.
    """
    import threading

    from insta_agent.web import Steuerung, _handler_klasse
    from http.server import ThreadingHTTPServer
    import urllib.request

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_klasse(Steuerung(settings), None)
    )
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/version", timeout=3) as a:
            text = a.read().decode("utf-8")
            assert a.headers.get("Content-Type", "").startswith("text/plain")
            assert "no-store" in a.headers.get("Cache-Control", "")

        assert "insta-agent" in text
        assert f"Port:   {port}" in text
        assert "Grenze:" in text
    finally:
        server.shutdown()
        server.server_close()


# --- Neue Bedienelemente --------------------------------------------------


def test_eine_einnahme_laesst_sich_ueber_die_oberflaeche_buchen(settings):
    """Schließt den Kreis: Geld empfängt ein Mensch, eintragen muss er es."""
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    from insta_agent.runner import Agent
    from insta_agent.web import Steuerung, _handler_klasse

    settings.anthropic_api_key = "sk-ant-test"
    steuerung = Steuerung(settings)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(steuerung, None))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        anfrage = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/einnahme",
            data=json.dumps({"betrag": 12.5, "kategorie": "digital_product", "notiz": "Vorlage"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(anfrage, timeout=5) as antwort:
            assert json.loads(antwort.read())["ok"] is True

        agent = Agent(settings)
        try:
            zustand = agent.treasury.state()
            assert zustand.earned_usd == 12.5
            # Das Startkapital gilt weiterhin nicht als Verdienst.
            assert zustand.seed_usd > 0
        finally:
            agent.close()
    finally:
        server.shutdown()
        server.server_close()


def test_ein_betrag_von_null_wird_abgelehnt(settings):
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from insta_agent.web import Steuerung, _handler_klasse

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(Steuerung(settings), None))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        anfrage = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/einnahme",
            data=json.dumps({"betrag": 0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as fehler:
            urllib.request.urlopen(anfrage, timeout=5)
        assert fehler.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_im_lesemodus_kann_niemand_von_aussen_geld_buchen(settings):
    """Sonst könnte jeder im WLAN die Kasse des Agenten verfälschen."""
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from insta_agent.web import Steuerung, _handler_klasse

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_klasse(Steuerung(settings, nur_lesen=True), None)
    )
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        anfrage = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/einnahme",
            data=json.dumps({"betrag": 99}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as fehler:
            urllib.request.urlopen(anfrage, timeout=5)
        assert fehler.value.code == 409
    finally:
        server.shutdown()
        server.server_close()


def test_das_portrait_ist_eine_grafik_und_kein_foto():
    """Ein erfundenes Gesicht würde Follower über den Absender täuschen."""
    from pathlib import Path
    import tempfile

    from PIL import Image

    from insta_agent.imaging.avatar import render_avatar

    with tempfile.TemporaryDirectory() as ordner:
        pfad = render_avatar("Jonas Rieck", Path(ordner) / "p.png", accent_hex="#F2C14E")
        with Image.open(pfad) as bild:
            assert bild.size == (512, 512)
            assert bild.mode == "RGBA"  # rund freigestellt

        # Gleicher Name, gleiches Bild - zwei Agenten sehen nie gleich aus.
        zweites = render_avatar("Jonas Rieck", Path(ordner) / "p2.png", accent_hex="#F2C14E")
        anderer = render_avatar("Mara Vogt", Path(ordner) / "p3.png", accent_hex="#F2C14E")
        assert pfad.read_bytes() == zweites.read_bytes()
        assert pfad.read_bytes() != anderer.read_bytes()


def test_ein_eigenes_portrait_hat_vorrang(settings, tmp_path, monkeypatch):
    """Das Dashboard sieht nur der Betreiber - er darf es gestalten."""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import insta_agent.web as web
    from insta_agent.web import Steuerung, _handler_klasse

    # Ein eigenes Bild in einem nachgestellten Projektordner.
    wurzel = tmp_path / "projekt"
    (wurzel / "assets").mkdir(parents=True)
    eigenes = b"\x89PNG\r\n\x1a\n" + b"mein-eigenes-bild"
    (wurzel / "assets" / "portrait.png").write_bytes(eigenes)
    monkeypatch.setattr("insta_agent.config.REPO_ROOT", wurzel)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(Steuerung(settings), None))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/avatar", timeout=5) as antwort:
            assert antwort.read() == eigenes
            assert antwort.headers.get("Content-Type") == "image/png"
    finally:
        server.shutdown()
        server.server_close()


def test_ohne_eigenes_portrait_und_ohne_profil_gibt_es_keins(settings, tmp_path, monkeypatch):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from insta_agent.web import Steuerung, _handler_klasse

    wurzel = tmp_path / "leer"
    (wurzel / "assets").mkdir(parents=True)
    monkeypatch.setattr("insta_agent.config.REPO_ROOT", wurzel)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(Steuerung(settings), None))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as fehler:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/avatar", timeout=5)
        assert fehler.value.code == 404
    finally:
        server.shutdown()
        server.server_close()



# --- Das Symbol im Browsertab ---------------------------------------------


def _laufender_server(settings):
    """Startet den echten Server auf einem freien Port."""
    import threading
    from http.server import ThreadingHTTPServer

    from insta_agent.web import Steuerung, _handler_klasse

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_klasse(Steuerung(settings), None)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_das_tabsymbol_kommt_vom_portrait(settings):
    """Sonst fragt jeder Browser /favicon.ico an und bekommt einen 404.

    Sichtbar wurde das als roter Fehler in der Browserkonsole. Nebenbei
    erkennt man an einem eigenen Symbol, welcher Tab das Dashboard ist.
    """
    import urllib.request

    from insta_agent.models import Identity
    from insta_agent.runner import KEY_IDENTITY
    from insta_agent.store import Store

    store = Store(settings.db_path)
    store.set_json(
        KEY_IDENTITY,
        Identity(
            agent_name="Jonas Rieck",
            agent_why="x",
            handle="vieruhrfreitag",
            display_name="Jonas Rieck",
            motto="x",
            niche="x",
            target_audience="x",
            tone_of_voice="x",
            visual_identity="x",
            content_pillars=["a", "b", "c"],
            bio="x",
            why_this_works="x",
        ).model_dump(mode="json"),
    )
    store.close()

    server = _laufender_server(settings)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/favicon.ico") as antwort:
            assert antwort.status == 200
            # PNG erkennt man an den ersten acht Bytes.
            assert antwort.read(8) == b"\x89PNG\r\n\x1a\n"
    finally:
        server.shutdown()
        server.server_close()


def test_die_seite_verlangt_das_portrait_als_tabsymbol():
    seite = (Path(__file__).resolve().parent.parent
             / "insta_agent" / "web_page.html").read_text("utf-8")
    assert '<link rel="icon" href="/avatar">' in seite


# --- Kontostand über die Oberfläche ---------------------------------------


def _sende(port: int, pfad: str, rumpf: dict):
    import json
    import urllib.request

    anfrage = urllib.request.Request(
        f"http://127.0.0.1:{port}{pfad}",
        data=json.dumps(rumpf).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(anfrage, timeout=5) as antwort:
        return json.loads(antwort.read())


def _server(settings):
    import threading
    from http.server import ThreadingHTTPServer

    from insta_agent.web import Steuerung, _handler_klasse

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(Steuerung(settings), None))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_der_kontostand_laesst_sich_ueber_die_oberflaeche_setzen(settings):
    """Nach dem Aufladen soll niemand ins schwarze Fenster müssen."""
    from insta_agent.runner import Agent

    settings.anthropic_api_key = "sk-ant-test"
    server, port = _server(settings)

    try:
        ergebnis = _sende(port, "/api/kasse", {"guthaben": 6.11})
        assert ergebnis["ok"] is True
        assert ergebnis["stand"] == 6.11

        agent = Agent(settings)
        try:
            stand = agent.treasury.state()
            assert stand.balance_usd == pytest.approx(6.11)
            # Nachgelegtes Geld ist kein Verdienst des Agenten.
            assert stand.earned_usd == 0.0
        finally:
            agent.close()
    finally:
        server.shutdown()
        server.server_close()


def test_ein_kontostand_der_keine_zahl_ist_wird_abgelehnt(settings):
    import urllib.error

    server, port = _server(settings)
    try:
        with pytest.raises(urllib.error.HTTPError) as fehler:
            _sende(port, "/api/kasse", {"guthaben": "viel"})
        assert fehler.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_ein_negativer_kontostand_wird_abgelehnt(settings):
    import urllib.error

    server, port = _server(settings)
    try:
        with pytest.raises(urllib.error.HTTPError) as fehler:
            _sende(port, "/api/kasse", {"guthaben": -1})
        assert fehler.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_die_nur_lese_ansicht_darf_die_kasse_nicht_anfassen(settings):
    """Vom Handy aus nachsehen, ja. Die Kasse verstellen, nein."""
    import urllib.error

    import threading
    from http.server import ThreadingHTTPServer

    from insta_agent.web import Steuerung, _handler_klasse

    steuerung = Steuerung(settings, nur_lesen=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(steuerung, None))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        with pytest.raises(urllib.error.HTTPError) as fehler:
            _sende(port, "/api/kasse", {"guthaben": 5.0})
        assert fehler.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
