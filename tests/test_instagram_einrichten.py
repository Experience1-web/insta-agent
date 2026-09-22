"""Der Weg vom kurzlebigen Token zum dauerhaften Zugang.

Jeder Schritt kann bei Meta anders scheitern. Geprüft wird vor allem,
dass der Betreiber dabei nie eine englische Fehlernummer sieht, sondern
einen Satz, der sagt, was zu tun ist.
"""

from __future__ import annotations

import httpx
import pytest

from insta_agent.instagram.einrichten import (
    Einrichtungsfehler,
    _uebersetze,
    richte_ein,
)

SEITE = {"id": "111", "name": "Zahl gegen Bauchgefühl", "access_token": "seiten-token"}


# Die Berechtigungen werden bei jedem Lauf abgefragt. Wo ein Test nichts
# anderes sagt, sind sie vollstaendig - hier geht es um die Seiten, nicht
# um die Rechte. Dass fehlende Rechte auffallen, prueft test_berechtigungen.
ALLE_RECHTE = {
    "data": [
        {"permission": "instagram_basic", "status": "granted"},
        {"permission": "instagram_content_publish", "status": "granted"},
        {"permission": "instagram_manage_insights", "status": "granted"},
        {"permission": "pages_show_list", "status": "granted"},
        {"permission": "pages_read_engagement", "status": "granted"},
    ]
}


def _antwortet(**routen):
    """Baut einen Transport, der je nach Pfad antwortet."""
    routen.setdefault("me/permissions", ALLE_RECHTE)

    def handler(request: httpx.Request) -> httpx.Response:
        for teil, antwort in routen.items():
            if teil in request.url.path:
                return httpx.Response(200, json=antwort)
        return httpx.Response(404, json={"error": {"message": f"kein Pfad {request.url.path}"}})

    return httpx.MockTransport(handler)


@pytest.fixture
def meta(monkeypatch):
    """Ersetzt den echten Meta-Server durch einen, den wir steuern."""

    def setze(**routen):
        transport = _antwortet(**routen)
        echt = httpx.Client
        monkeypatch.setattr(
            "insta_agent.instagram.einrichten.httpx.Client",
            lambda **k: echt(transport=transport, **k),
        )

    return setze


def test_der_ganze_weg_geht_durch(meta):
    meta(
        **{
            "oauth/access_token": {"access_token": "langer-token"},
            "me/accounts": {"data": [SEITE]},
            "/111": {"instagram_business_account": {"id": "999"}},
            "/999": {"username": "zahlgegenbauchgefuehl", "followers_count": 0},
        }
    )

    zugang = richte_ein("kurz", "app-id", "geheim")

    assert zugang.ig_user_id == "999"
    assert zugang.seiten_token == "seiten-token"
    assert zugang.handle == "zahlgegenbauchgefuehl"
    assert zugang.seiten_name == "Zahl gegen Bauchgefühl"


def test_ohne_facebook_seite_kommt_ein_klarer_hinweis(meta):
    meta(**{"oauth/access_token": {"access_token": "lang"}, "me/accounts": {"data": []}})

    with pytest.raises(Einrichtungsfehler, match="keine Facebook-Seite"):
        richte_ein("kurz", "app-id", "geheim")


def test_seite_ohne_instagram_nennt_die_loesung(meta):
    meta(
        **{
            "oauth/access_token": {"access_token": "lang"},
            "me/accounts": {"data": [SEITE]},
            "/111": {},  # keine instagram_business_account
        }
    )

    with pytest.raises(Einrichtungsfehler) as fehler:
        richte_ein("kurz", "app-id", "geheim")

    text = str(fehler.value)
    assert "Zahl gegen Bauchgefühl" in text
    assert "linked_instagram" in text


def test_die_richtige_seite_wird_aus_mehreren_gefunden(meta):
    """Wer mehrere Seiten hat, soll nicht raten muessen."""
    ohne = {"id": "222", "name": "Alte Seite", "access_token": "token-222"}
    meta(
        **{
            "oauth/access_token": {"access_token": "lang"},
            "me/accounts": {"data": [ohne, SEITE]},
            "/222": {},
            "/111": {"instagram_business_account": {"id": "999"}},
            "/999": {"username": "konrad", "followers_count": 3},
        }
    )

    zugang = richte_ein("kurz", "app-id", "geheim")

    assert zugang.ig_user_id == "999"
    assert zugang.seiten_name == "Zahl gegen Bauchgefühl"


def test_ein_fehlgeschlagener_tausch_wird_erklaert(meta):
    meta(**{"oauth/access_token": {}})

    with pytest.raises(Einrichtungsfehler, match="App-ID und App-Geheimnis"):
        richte_ein("kurz", "falsch", "falsch")


# --- Metas Fehlernummern in verstaendliche Saetze -------------------------


def test_abgelaufener_token():
    text = _uebersetze({"code": 190, "message": "Session has expired"})
    assert "abgelaufen" in text
    assert "ein bis zwei Stunden" in text


def test_fehlende_berechtigung_nennt_die_haken():
    text = _uebersetze({"code": 200, "message": "Permissions error"})
    assert "instagram_content_publish" in text
    assert "pages_show_list" in text


def test_ein_unbekannter_code_geht_nicht_verloren():
    text = _uebersetze({"code": 4711, "message": "Etwas ganz Neues"})
    assert "Etwas ganz Neues" in text


# --- Kennzahlen ohne Berechtigung ------------------------------------------


def test_fehlende_kennzahl_berechtigung_wird_erklaert():
    """"(#10) Application does not have permission" sagt nicht, welche fehlt."""
    from insta_agent.instagram.client import GraphAPIError, kennzahlgrund

    grund = kennzahlgrund(
        GraphAPIError("OAuthException 10: (#10) Application does not have permission for this action")
    )

    assert "instagram_manage_insights" in grund
    assert "insta-agent instagram" in grund


def test_ein_abgelaufenes_zugangswort_wird_als_solches_erkannt():
    from insta_agent.instagram.client import GraphAPIError, kennzahlgrund

    assert "abgelaufen" in kennzahlgrund(GraphAPIError("OAuthException 190: Session expired"))


def test_ein_unbekannter_grund_geht_unveraendert_durch():
    """Lieber eine englische Meldung als eine falsche deutsche."""
    from insta_agent.instagram.client import GraphAPIError, kennzahlgrund

    assert kennzahlgrund(GraphAPIError("Etwas ganz anderes")) == "Etwas ganz anderes"


def test_die_einrichtung_nennt_die_berechtigung_von_anfang_an():
    """Sonst richtet man sie ein und merkt erst Tage spaeter, dass sie fehlt."""
    import inspect

    from insta_agent import cli

    quelle = inspect.getsource(cli.instagram)
    assert "instagram_manage_insights" in quelle


def test_ein_verschwundener_beitrag_wird_verstaendlich_gemeldet():
    """Aus dem Betrieb: Code 100, "Object with ID ... does not exist".

    Roh im Protokoll sah das aus wie ein Absturz, mitten im Zyklus. Es ist
    keiner - und es ist auch nicht die fehlende Berechtigung, die kommt
    als Code 10.
    """
    from insta_agent.instagram.client import kennzahlgrund

    roh = Exception(
        "GraphMethodException 100: Unsupported get request. Object with ID "
        "'18267799759307148' does not exist, cannot be loaded due to missing "
        "permissions, or does not support this operation."
    )
    satz = kennzahlgrund(roh)
    assert "gelöscht" in satz
    assert "läuft weiter" in satz
    assert "Berechtigung" not in satz


def test_die_fehlende_berechtigung_bleibt_die_fehlende_berechtigung():
    from insta_agent.instagram.client import kennzahlgrund

    satz = kennzahlgrund(Exception("(#10) Application does not have permission"))
    assert "Berechtigung fehlt" in satz
