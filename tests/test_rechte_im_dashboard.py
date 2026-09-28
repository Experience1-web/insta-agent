# ruff: noqa: F811 - settings ist eine Fixture aus test_cycle
"""Das Dashboard sieht selbst nach, was der Instagram-Zugang darf.

Vorher ging das nur über "16 - Instagram-Rechte pruefen" zum Doppelklicken.
Wer nicht wusste, dass es die Datei gibt, erfuhr nie, dass dem Agenten die
Kennzahlen fehlen.
"""

from __future__ import annotations

import time

from insta_agent.instagram.einrichten import fehlende_rechte
from insta_agent.web import Steuerung
from test_cycle import settings  # noqa: F401 - Fixture


def _mit_zugang(settings):
    settings.ig_access_token = "token"
    settings.meta_app_id = "app"
    settings.meta_app_secret = "geheim"
    return settings


def test_gleichwertige_rechte_zaehlen_mit():
    alle = [
        "instagram_basic",
        "instagram_content_publish",
        "pages_show_list",
        "pages_read_engagement",
    ]
    assert fehlende_rechte(alle) == ["instagram_manage_insights"]
    assert fehlende_rechte([*alle, "instagram_business_manage_insights"]) == []


def test_ohne_zugang_wird_nichts_geprueft(settings):
    assert Steuerung(settings).rechte_stand() is None


def test_fehlende_berechtigung_steht_im_stand(settings, monkeypatch):
    monkeypatch.setattr(
        "insta_agent.instagram.einrichten.pruefe_rechte",
        lambda *a: (("instagram_basic", "instagram_content_publish"), ""),
    )
    steuerung = Steuerung(_mit_zugang(settings))

    stand = steuerung.pruefe_rechte_jetzt()

    fehlt = [f["recht"] for f in stand["fehlt"]]
    assert "instagram_manage_insights" in fehlt
    assert stand["grund"] == ""


def test_der_stand_kommt_im_hintergrund_und_wird_gemerkt(settings, monkeypatch):
    aufrufe = []

    def frage(*a):
        aufrufe.append(1)
        return ("instagram_basic",), ""

    monkeypatch.setattr("insta_agent.instagram.einrichten.pruefe_rechte", frage)
    steuerung = Steuerung(_mit_zugang(settings))

    steuerung.rechte_stand()  # stösst die Prüfung im Hintergrund an
    for _ in range(50):
        if steuerung.rechte_stand() is not None:
            break
        time.sleep(0.02)
    assert steuerung.rechte_stand()["fehlt"]
    steuerung.rechte_stand()
    assert len(aufrufe) == 1  # gemerkt, nicht bei jedem Auffrischen gefragt


def test_ein_netzfehler_wird_zum_grund(settings, monkeypatch):
    def kaputt(*a):
        raise OSError("weg")

    monkeypatch.setattr("insta_agent.instagram.einrichten.pruefe_rechte", kaputt)

    stand = Steuerung(_mit_zugang(settings)).pruefe_rechte_jetzt()

    assert "nicht erreichbar" in stand["grund"]
    assert stand["fehlt"] == []
