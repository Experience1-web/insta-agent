"""Was schon eingerichtet ist, muss sichtbar sein.

Der Betreiber hat mehrere Bilddienste nacheinander ausprobiert und
irgendwann gefragt: "Haben wir da nicht schon mal einen Schlüssel
eingetippt?" Die Frage ist berechtigt, und das Programm konnte sie nicht
beantworten - es fragte nur wieder.

Also: Beim Einrichten steht zuerst da, wer gerade malt und ob ein
Schlüssel hinterlegt ist. Und wer beim selben Anbieter bleibt, darf die
Eingabe leer lassen.
"""

from __future__ import annotations

from insta_agent.cli import _alter_schluessel, _verkuerzt


class Bild:
    def __init__(self, anbieter="", token="", modell=""):
        self.anbieter = anbieter
        self.token = token
        self.modell = modell


class Einstellungen:
    def __init__(self, bild):
        self.bild = bild


def _mit(monkeypatch, anbieter="", token=""):
    monkeypatch.setattr(
        "insta_agent.cli.load_settings",
        lambda *a, **k: Einstellungen(Bild(anbieter, token)),
    )


# --- Was angezeigt wird ----------------------------------------------------


def test_vom_schluessel_sieht_man_nur_das_ende():
    """Genug zum Wiedererkennen, zu wenig zum Missbrauchen."""
    gekuerzt = _verkuerzt("AIzaSyD-geheim-geheim-abcd")

    assert gekuerzt == "...abcd"
    assert "geheim" not in gekuerzt


def test_ein_kurzer_schluessel_wird_gar_nicht_gezeigt():
    assert _verkuerzt("kurz123") == "(kurz)"


def test_ohne_schluessel_bleibt_es_leer():
    assert _verkuerzt("") == ""
    assert _verkuerzt(None) == ""


# --- Welcher Schlüssel weitergilt ------------------------------------------


def test_beim_selben_anbieter_gilt_der_alte_weiter(monkeypatch):
    _mit(monkeypatch, "gemini", "AIza-alt-alt-alt")

    assert _alter_schluessel(None, "gemini") == "AIza-alt-alt-alt"


def test_bei_einem_anderen_anbieter_nicht(monkeypatch):
    """Ein Cloudflare-Schlüssel taugt nicht für Gemini."""
    _mit(monkeypatch, "cloudflare", "konto:schluessel")

    assert _alter_schluessel(None, "gemini") == ""


def test_ohne_eingerichteten_dienst_gibt_es_nichts(monkeypatch):
    _mit(monkeypatch, "", "")

    assert _alter_schluessel(None, "gemini") == ""


def test_kaputte_einstellungen_halten_nichts_auf(monkeypatch):
    def platzt(*a, **k):
        raise RuntimeError("keine .env")

    monkeypatch.setattr("insta_agent.cli.load_settings", platzt)

    assert _alter_schluessel(None, "gemini") == ""


# --- Die Anzeige selbst ----------------------------------------------------


def test_der_stand_nennt_den_anbieter_im_klartext(monkeypatch, capsys):
    from insta_agent.cli import _zeige_bildstand

    _mit(monkeypatch, "gemini", "AIzaSyD-geheim-abcd")
    _zeige_bildstand(None)

    ausgabe = capsys.readouterr().out
    assert "Google Gemini" in ausgabe
    assert "...abcd" in ausgabe
    # Der ganze Schlüssel gehört nicht auf den Bildschirm.
    assert "geheim" not in ausgabe


def test_ohne_dienst_sagt_der_stand_das_auch(monkeypatch, capsys):
    from insta_agent.cli import _zeige_bildstand

    _mit(monkeypatch, "", "")
    _zeige_bildstand(None)

    assert "kein Bilddienst" in capsys.readouterr().out


def test_bei_pollinations_steht_kein_schluessel_noetig(monkeypatch, capsys):
    from insta_agent.cli import _zeige_bildstand

    _mit(monkeypatch, "pollinations", "")
    _zeige_bildstand(None)

    ausgabe = capsys.readouterr().out
    assert "Pollinations" in ausgabe
    assert "keiner noetig" in ausgabe
