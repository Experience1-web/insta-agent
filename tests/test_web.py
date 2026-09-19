"""Die Oberfläche darf keine Datei ausliefern, die ihr nicht gehört."""

import json

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


def test_fremdes_programm_auf_dem_port_wird_nicht_abgeschossen(settings, capsys):
    """Ein belegter Port heißt nicht, dass dort unser Dashboard läuft.

    Ohne diese Unterscheidung würde das Aufräumen irgendein fremdes
    Programm beenden - hier war es der Testlauf selbst.
    """
    import socket

    from insta_agent.web import starte_server

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]

    try:
        with pytest.raises(SystemExit):
            starte_server(settings, port=port, oeffnen=False)
        ausgabe = capsys.readouterr().out
        assert "anderen Programm belegt" in ausgabe
        assert "--port" in ausgabe, "es fehlt der Ausweg"
    finally:
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
