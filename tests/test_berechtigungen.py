"""Fehlende Instagram-Berechtigungen müssen sofort auffallen.

Meta beschwert sich nicht über fehlende Rechte. Es liefert die
betroffenen Felder einfach nicht mit - die Antwort sieht aus wie eine
gültige Antwort, nur ohne Reichweite und ohne Speicherungen. Wer das
nicht gegenprüft, merkt Wochen später, dass der Agent nie Zahlen hatte
und deshalb nie etwas gelernt hat.

Genau das ist hier passiert. Also wird beim Einrichten nachgesehen.
"""

from __future__ import annotations

import httpx
import pytest

from insta_agent.instagram.einrichten import (
    NOETIGE_RECHTE,
    Einrichtungsfehler,
    Zugang,
    richte_ein,
)


def _antworten(erteilt: list[str]):
    """Ein Meta, das genau diese Berechtigungen erteilt hat."""

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        pfad = anfrage.url.path
        if pfad.endswith("oauth/access_token"):
            return httpx.Response(200, json={"access_token": "langer-token"})
        if pfad.endswith("me/permissions"):
            return httpx.Response(
                200,
                json={"data": [{"permission": r, "status": "granted"} for r in erteilt]},
            )
        if pfad.endswith("me/accounts"):
            return httpx.Response(
                200,
                json={"data": [{"id": "77", "name": "Meine Seite", "access_token": "seiten-token"}]},
            )
        if pfad.endswith("/77"):
            return httpx.Response(200, json={"instagram_business_account": {"id": "4242"}})
        if pfad.endswith("/4242"):
            return httpx.Response(200, json={"username": "erstfund", "followers_count": 12})
        return httpx.Response(404, json={"error": {"message": "unbekannt", "code": 100}})

    return antworte


@pytest.fixture
def meta(monkeypatch):
    def baue(erteilt):
        transport = httpx.MockTransport(_antworten(erteilt))
        echter = httpx.Client

        def gefaelscht(*a, **k):
            k["transport"] = transport
            return echter(*a, **k)

        monkeypatch.setattr("insta_agent.instagram.einrichten.httpx.Client", gefaelscht)

    return baue


def test_mit_allen_rechten_fehlt_nichts(meta):
    meta(list(NOETIGE_RECHTE))

    zugang = richte_ein("kurz", "app", "geheim")

    assert zugang.fehlend == ()
    assert zugang.handle == "erstfund"


def test_die_fehlende_berechtigung_wird_benannt(meta):
    """Ohne instagram_manage_insights lernt er nichts aus seinen Zahlen."""
    meta(["instagram_basic", "instagram_content_publish", "pages_show_list"])

    zugang = richte_ein("kurz", "app", "geheim")

    assert "instagram_manage_insights" in zugang.fehlend
    assert "pages_read_engagement" in zugang.fehlend
    assert "instagram_basic" not in zugang.fehlend


def test_die_einrichtung_laeuft_trotzdem_durch(meta):
    """Posten geht ja - nur lernen nicht. Das ist kein Grund abzubrechen."""
    meta(["instagram_basic", "instagram_content_publish", "pages_show_list"])

    zugang = richte_ein("kurz", "app", "geheim")

    assert zugang.ig_user_id == "4242"
    assert zugang.seiten_token == "seiten-token"


def test_nur_wirklich_erteiltes_zaehlt(monkeypatch):
    """Meta fuehrt abgelehnte Rechte mit auf - als 'declined'."""

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        pfad = anfrage.url.path
        if pfad.endswith("oauth/access_token"):
            return httpx.Response(200, json={"access_token": "langer-token"})
        if pfad.endswith("me/permissions"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"permission": "instagram_basic", "status": "granted"},
                        {"permission": "instagram_manage_insights", "status": "declined"},
                    ]
                },
            )
        if pfad.endswith("me/accounts"):
            return httpx.Response(
                200,
                json={"data": [{"id": "77", "name": "S", "access_token": "t"}]},
            )
        if pfad.endswith("/77"):
            return httpx.Response(200, json={"instagram_business_account": {"id": "4242"}})
        return httpx.Response(200, json={"username": "x", "followers_count": 0})

    transport = httpx.MockTransport(antworte)
    echter = httpx.Client
    monkeypatch.setattr(
        "insta_agent.instagram.einrichten.httpx.Client",
        lambda *a, **k: echter(*a, **{**k, "transport": transport}),
    )

    zugang = richte_ein("kurz", "app", "geheim")

    assert "instagram_manage_insights" in zugang.fehlend


def test_jede_noetige_berechtigung_hat_eine_begruendung():
    """Ein Name allein sagt dem Betreiber nicht, warum er sie braucht."""
    for recht, wozu in NOETIGE_RECHTE.items():
        assert recht.startswith(("instagram_", "pages_"))
        assert len(wozu) > 10


def test_ein_abgelaufener_token_wird_erklaert(monkeypatch):
    def antworte(anfrage: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "Session expired", "code": 190}}
        )

    transport = httpx.MockTransport(antworte)
    echter = httpx.Client
    monkeypatch.setattr(
        "insta_agent.instagram.einrichten.httpx.Client",
        lambda *a, **k: echter(*a, **{**k, "transport": transport}),
    )

    with pytest.raises(Einrichtungsfehler) as fehler:
        richte_ein("alt", "app", "geheim")

    assert "abgelaufen" in str(fehler.value)


def test_ohne_angabe_gilt_nichts_als_erteilt():
    assert len(Zugang("1", "t", "S", "h", 0).fehlend) == len(NOETIGE_RECHTE)
