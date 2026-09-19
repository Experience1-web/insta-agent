"""Der Autostart muss sich genauso leicht wieder abschalten lassen."""

import pytest

from insta_agent import windows


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    return tmp_path / "AppData" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def test_einschalten_legt_die_startdatei_an(appdata):
    assert not windows.ist_eingeschaltet()

    ergebnis = windows.einschalten()
    assert ergebnis.erfolg
    assert windows.ist_eingeschaltet()

    datei = appdata / windows.DATEINAME
    inhalt = datei.read_text(encoding="utf-8")
    assert "insta_agent.cli web" in inhalt
    # Ohne UTF-8 werden Umlaute im schwarzen Fenster zu Fragezeichen.
    assert "chcp 65001" in inhalt
    # Ohne py-Erkennung scheitert es auf Rechnern, die nur `python` kennen.
    assert "if errorlevel 1 set PY=python" in inhalt
    # Zeilenenden müssen Windows-Stil haben, sonst stolpert die Eingabeaufforderung.
    assert b"\r\n" in datei.read_bytes()


def test_handy_variante_lauscht_nach_aussen_aber_nur_lesend(appdata):
    windows.einschalten(host="0.0.0.0", nur_lesen=True)
    inhalt = (appdata / windows.DATEINAME).read_text(encoding="utf-8")
    assert "--host 0.0.0.0" in inhalt
    assert "--read-only" in inhalt


def test_ausschalten_entfernt_die_datei(appdata):
    windows.einschalten()
    assert windows.ausschalten().erfolg
    assert not windows.ist_eingeschaltet()


def test_zweimal_ausschalten_ist_kein_fehler(appdata):
    windows.ausschalten()
    ergebnis = windows.ausschalten()
    assert ergebnis.erfolg
    assert "gar nicht" in ergebnis.nachricht


def test_ohne_appdata_wird_sauber_abgelehnt(monkeypatch):
    """Auf Mac und Linux gibt es diesen Ordner nicht."""
    monkeypatch.delenv("APPDATA", raising=False)

    assert windows.autostart_ordner() is None
    assert not windows.ist_eingeschaltet()
    for ergebnis in (windows.einschalten(), windows.ausschalten()):
        assert not ergebnis.erfolg
        assert "Windows" in ergebnis.nachricht
