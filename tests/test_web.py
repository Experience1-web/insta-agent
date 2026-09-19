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
