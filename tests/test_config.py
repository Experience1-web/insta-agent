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


# --- Schreiben in die .env ------------------------------------------------


def test_platzhalter_wird_ersetzt_nicht_verdoppelt(tmp_path):
    from insta_agent.config import set_env_value

    env = tmp_path / ".env"
    env.write_text(
        "# Kommentar\nANTHROPIC_API_KEY=sk-ant-...\nIG_USER_ID=\n", encoding="utf-8"
    )
    set_env_value("ANTHROPIC_API_KEY", "sk-ant-echt", path=env)

    inhalt = env.read_text(encoding="utf-8")
    assert inhalt.count("ANTHROPIC_API_KEY") == 1
    assert "sk-ant-echt" in inhalt
    assert "IG_USER_ID=" in inhalt  # andere Zeilen bleiben unangetastet


def test_auskommentierte_zeile_wird_ersetzt(tmp_path):
    """#TREASURY_START_USD=5.00 soll aktiviert, nicht dupliziert werden."""
    from insta_agent.config import set_env_value

    env = tmp_path / ".env"
    env.write_text("#TREASURY_START_USD=5.00\n", encoding="utf-8")
    set_env_value("TREASURY_START_USD", "12.00", path=env)

    inhalt = env.read_text(encoding="utf-8")
    assert inhalt.count("TREASURY_START_USD") == 1
    assert inhalt.strip() == "TREASURY_START_USD=12.00"


def test_neuer_schluessel_wird_angehaengt(tmp_path):
    from insta_agent.config import set_env_value

    env = tmp_path / ".env"
    env.write_text("IG_USER_ID=123\n", encoding="utf-8")
    set_env_value("ANTHROPIC_API_KEY", "sk-ant-neu", path=env)

    inhalt = env.read_text(encoding="utf-8")
    assert "IG_USER_ID=123" in inhalt
    assert "ANTHROPIC_API_KEY=sk-ant-neu" in inhalt


def test_geschriebener_wert_wird_wieder_gelesen(tmp_path):
    """Die Gegenprobe, die `insta-agent setup` selbst durchführt."""
    from insta_agent.config import _load_dotenv, set_env_value

    env = tmp_path / ".env"
    set_env_value("ANTHROPIC_API_KEY", "sk-ant-rundlauf", path=env)
    _load_dotenv(env)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-rundlauf"


def test_zeilenumbruch_im_wert_wird_abgelehnt(tmp_path):
    """Ein Umbruch würde die Datei zerreißen - lieber sofort scheitern."""
    from insta_agent.config import set_env_value

    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-...\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Zeilenumbruch"):
        set_env_value("ANTHROPIC_API_KEY", "sk-ant-abc\ndef", path=env)

    # Die Datei bleibt unangetastet.
    assert env.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=sk-ant-...\n"


def test_mehrzeilige_eingabe_wird_zu_einer_zeile_zusammengezogen():
    """Was `insta-agent setup` mit einer Einfügung aus der Zwischenablage macht."""
    roh = "sk-ant-abc123\ndef456\n"
    assert "".join(roh.split()) == "sk-ant-abc123def456"

    # Auch Leerzeichen und Tabs verschwinden.
    assert "".join("  sk-ant-x y\tz ".split()) == "sk-ant-xyz"
