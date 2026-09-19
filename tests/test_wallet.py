"""Der Agent bekommt eine Empfangsadresse - und niemals einen Schlüssel."""

import pytest

from insta_agent.wallet import (
    hinweis_fuer_den_agenten,
    maskiere,
    pruefe_adresse,
    sieht_nach_geheimnis_aus,
)


def test_normale_empfangsadresse_wird_angenommen():
    assert pruefe_adresse("0x" + "a" * 40, "base").ok


def test_privater_schluessel_wird_erkannt():
    """64 Hexzeichen sind ein Schlüssel. Wer ihn einträgt, verliert sein Geld."""
    pruefung = pruefe_adresse("0x" + "a" * 64, "ethereum")
    assert not pruefung.ok
    assert "privater Schlüssel" in pruefung.grund


def test_schluessel_auch_ohne_praefix_erkannt():
    assert not sieht_nach_geheimnis_aus("b" * 64).ok


@pytest.mark.parametrize("anzahl", [12, 15, 18, 21, 24])
def test_wiederherstellungswoerter_werden_erkannt(anzahl):
    saat = " ".join(["abandon"] * anzahl)
    pruefung = sieht_nach_geheimnis_aus(saat)
    assert not pruefung.ok
    assert "Wiederherstellungswörter" in pruefung.grund


def test_ein_normaler_satz_gilt_nicht_als_saat():
    """Zwölf Wörter allein machen noch keine Wallet."""
    assert sieht_nach_geheimnis_aus("das ist ein ganz normaler satz mit genau zwoelf woertern drin").ok


def test_tippfehler_in_der_adresse_faellt_auf():
    pruefung = pruefe_adresse("0xabc", "ethereum")
    assert not pruefung.ok
    assert "40 Zeichen" in pruefung.grund


def test_unbekannte_kette_wird_nur_grob_geprueft():
    assert pruefe_adresse("bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", "bitcoin").ok
    assert not pruefe_adresse("kurz", "bitcoin").ok


def test_die_anzeige_verraet_nicht_die_ganze_adresse():
    adresse = "0x" + "a" * 40
    gekuerzt = maskiere(adresse)
    assert gekuerzt != adresse
    assert gekuerzt.startswith("0xaaaaaa")


def test_ohne_wallet_weiss_der_agent_dass_nichts_ankommen_kann():
    text = hinweis_fuer_den_agenten(None, None)
    assert "kein Konto" in text
    assert "theoretisch" in text


def test_mit_wallet_weiss_er_dass_er_nicht_senden_kann():
    """Sonst plant er Ausgaben, die er gar nicht tätigen kann."""
    text = hinweis_fuer_den_agenten("0x" + "a" * 40, "base")
    # Zeilenumbrüche im Prompt zusammenziehen, sonst prüft man die Umbrüche.
    fliesstext = " ".join(text.split())
    assert "nichts senden, nur empfangen" in fliesstext
    assert "keinen Zugriff auf die Schlüssel" in fliesstext
    # Die volle Adresse gehört auch hier nicht hinein.
    assert "a" * 40 not in text
