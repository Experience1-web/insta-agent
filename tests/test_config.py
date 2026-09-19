"""Das Laden der .env - hier entstehen die Fehler, die niemand findet."""

import os

import pytest

from insta_agent.config import EconomyConfig, _load_dotenv, _warn_about_unusable_budget


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "IG_USER_ID", "TREASURY_START_USD"):
        monkeypatch.delenv(key, raising=False)


def test_die_letzte_zeile_gewinnt(tmp_path, monkeypatch):
    """Der typische Fall: echter Schlüssel unter den Platzhalter gehängt."""
    env = tmp_path / ".env"
    env.write_text(
        "ANTHROPIC_API_KEY=sk-ant-...\n"
        "ANTHROPIC_API_KEY=sk-ant-echter-schluessel\n",
        encoding="utf-8",
    )
    _load_dotenv(env)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-echter-schluessel"


def test_echte_umgebungsvariable_schlaegt_die_datei(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "aus-der-umgebung")
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=aus-der-datei\n", encoding="utf-8")
    _load_dotenv(env)
    assert os.environ["ANTHROPIC_API_KEY"] == "aus-der-umgebung"


def test_kommentare_und_leerzeilen_werden_uebergangen(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# ein Kommentar\n"
        "\n"
        "#TREASURY_START_USD=99.00\n"
        "IG_USER_ID=12345\n",
        encoding="utf-8",
    )
    _load_dotenv(env)
    assert os.environ["IG_USER_ID"] == "12345"
    assert "TREASURY_START_USD" not in os.environ


def test_anfuehrungszeichen_werden_entfernt(tmp_path):
    env = tmp_path / ".env"
    env.write_text('IG_USER_ID="12345"\n', encoding="utf-8")
    _load_dotenv(env)
    assert os.environ["IG_USER_ID"] == "12345"


def test_fehlende_datei_ist_kein_fehler(tmp_path):
    _load_dotenv(tmp_path / "gibt-es-nicht")


def test_warnung_bei_schwellen_die_sich_aufheben(caplog):
    """Startkapital unter der Sparschwelle heißt: sofort gedrosselt."""
    with caplog.at_level("WARNING"):
        _warn_about_unusable_budget(
            EconomyConfig(treasury_start_usd=5.0, low_balance_usd=5.0, halt_balance_usd=0.5)
        )
    assert "Sparbetrieb" in caplog.text


def test_keine_warnung_bei_stimmigen_schwellen(caplog):
    with caplog.at_level("WARNING"):
        _warn_about_unusable_budget(
            EconomyConfig(treasury_start_usd=5.0, low_balance_usd=1.5, halt_balance_usd=0.25)
        )
    assert caplog.text == ""
