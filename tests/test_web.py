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
