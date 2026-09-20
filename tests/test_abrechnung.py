"""Die echte Abrechnung lesen, statt die Kosten zu schätzen.

Der heikle Teil ist die Einheit: Beträge kommen in Cent als Zeichenkette.
Ein Faktor 100 an dieser Stelle würde die Budgetbremse entweder nie oder
viel zu früh auslösen - beides fällt erst auf, wenn es zu spät ist.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from insta_agent.economy.abrechnung import (
    Abrechnung,
    Abrechnungsfehler,
    baue_abrechnung,
    tagesbeginn,
)


def _abrechnung(handler) -> Abrechnung:
    a = Abrechnung("sk-ant-admin-test")
    a.client = httpx.Client(transport=httpx.MockTransport(handler))
    return a


def _topf(*betraege: str) -> dict:
    return {
        "starting_at": "2026-09-19T00:00:00Z",
        "ending_at": "2026-09-20T00:00:00Z",
        "results": [{"amount": b, "currency": "USD"} for b in betraege],
    }


JETZT = datetime(2026, 9, 20, 15, 37, tzinfo=timezone.utc)


def test_betraege_kommen_in_cent_und_werden_zu_dollar():
    """"123.45" in USD sind 1,2345 Dollar - nicht 123."""

    def antworte(request):
        return httpx.Response(200, json={"data": [_topf("123.45")], "has_more": False})

    assert _abrechnung(antworte).kosten_seit(JETZT) == pytest.approx(1.2345)


def test_alle_posten_aller_toepfe_werden_addiert():
    def antworte(request):
        return httpx.Response(
            200,
            json={"data": [_topf("100", "50"), _topf("25")], "has_more": False},
        )

    assert _abrechnung(antworte).kosten_seit(JETZT) == pytest.approx(1.75)


def test_leere_tage_stoeren_nicht():
    def antworte(request):
        return httpx.Response(
            200, json={"data": [{"results": []}, _topf("200")], "has_more": False}
        )

    assert _abrechnung(antworte).kosten_seit(JETZT) == pytest.approx(2.0)


def test_es_wird_geblaettert_bis_nichts_mehr_kommt():
    seiten = []

    def antworte(request):
        seiten.append(request.url.params.get("page"))
        if len(seiten) == 1:
            return httpx.Response(
                200, json={"data": [_topf("100")], "has_more": True, "next_page": "p2"}
            )
        return httpx.Response(200, json={"data": [_topf("100")], "has_more": False})

    assert _abrechnung(antworte).kosten_seit(JETZT) == pytest.approx(2.0)
    assert seiten == [None, "p2"]


def test_eine_seite_ohne_folgemarke_beendet_das_blaettern():
    """Sonst liefe die Schleife ewig, wenn der Dienst sich widerspricht."""
    aufrufe = []

    def antworte(request):
        aufrufe.append(1)
        return httpx.Response(
            200, json={"data": [_topf("100")], "has_more": True, "next_page": None}
        )

    assert _abrechnung(antworte).kosten_seit(JETZT) == pytest.approx(1.0)
    assert len(aufrufe) == 1


def test_gefragt_wird_ab_dem_tagesbeginn():
    """Feiner als einen Tag rechnet die Abrechnung nicht ab."""
    gesehen: dict[str, str] = {}

    def antworte(request):
        gesehen.update(dict(request.url.params))
        return httpx.Response(200, json={"data": [], "has_more": False})

    _abrechnung(antworte).kosten_seit(JETZT)

    assert gesehen["starting_at"] == "2026-09-20T00:00:00Z"
    assert gesehen["bucket_width"] == "1d"


def test_der_schluessel_geht_im_kopf_mit():
    gesehen: dict[str, str] = {}

    def antworte(request):
        gesehen.update(dict(request.headers))
        return httpx.Response(200, json={"data": [], "has_more": False})

    _abrechnung(antworte).kosten_seit(JETZT)

    assert gesehen["x-api-key"] == "sk-ant-admin-test"
    assert gesehen["anthropic-version"] == "2023-06-01"


def test_ein_unlesbarer_betrag_kippt_nicht_die_summe():
    def antworte(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"results": [{"amount": "kaputt", "currency": "USD"}, *_topf("100")["results"]]}
                ],
                "has_more": False,
            },
        )

    assert _abrechnung(antworte).kosten_seit(JETZT) == pytest.approx(1.0)


def test_fremde_waehrung_wird_uebergangen():
    def antworte(request):
        return httpx.Response(
            200,
            json={
                "data": [{"results": [{"amount": "500", "currency": "EUR"}]}],
                "has_more": False,
            },
        )

    assert _abrechnung(antworte).kosten_seit(JETZT) == 0.0


def test_ein_zurueckgewiesener_schluessel_sagt_wo_es_weitergeht():
    """Die Meldung muss fuer beide Schluesselarten stimmen - sie weiss nicht,
    welcher gerade versucht wurde."""
    a = _abrechnung(lambda r: httpx.Response(403, json={"error": "forbidden"}))

    with pytest.raises(Abrechnungsfehler, match="admin-keys"):
        a.kosten_seit(JETZT)


def test_ohne_schluessel_gibt_es_keine_abrechnung():
    assert baue_abrechnung(None) is None
    assert baue_abrechnung("") is None
    assert baue_abrechnung("sk-ant-admin-x") is not None


def test_der_tagesbeginn_liegt_in_utc():
    mittags = datetime(2026, 9, 20, 13, 45, 12, tzinfo=timezone(timedelta(hours=2)))

    assert tagesbeginn(mittags) == datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)


# --- Zusammenspiel mit der Kasse ------------------------------------------


class FesteAbrechnung:
    def __init__(self, kosten: float):
        self.kosten = kosten
        self.gefragt: list[datetime] = []

    def kosten_seit(self, beginn):
        self.gefragt.append(beginn)
        return self.kosten


def test_ohne_anker_wird_nichts_fortgeschrieben(treasury):
    """Es fehlt der Bezugspunkt - dann bleibt die Schätzung stehen."""
    assert treasury.aus_abrechnung(FesteAbrechnung(1.0)) is None
    assert not treasury.rechnet_selbst()


def test_mit_anker_folgt_der_stand_der_echten_abrechnung(treasury):
    treasury.setze_anker(5.0, bereits_heute=0.0)

    treasury.aus_abrechnung(FesteAbrechnung(1.25))

    assert treasury.state().balance_usd == pytest.approx(3.75)


def test_was_vor_dem_ankern_anfiel_geht_nicht_zweimal_ab(treasury):
    """Die Abrechnung kennt nur ganze Tage, der Anker steht mittendrin."""
    treasury.setze_anker(5.0, bereits_heute=2.0)

    treasury.aus_abrechnung(FesteAbrechnung(2.0))  # seitdem nichts dazu

    assert treasury.state().balance_usd == pytest.approx(5.0)


def test_zweimal_nachfuehren_zieht_nicht_zweimal_ab(treasury):
    treasury.setze_anker(5.0, bereits_heute=0.0)
    abrechnung = FesteAbrechnung(1.0)

    treasury.aus_abrechnung(abrechnung)
    treasury.aus_abrechnung(abrechnung)

    assert treasury.state().balance_usd == pytest.approx(4.0)


def test_ein_anker_ohne_tagesstand_laesst_es_beim_eintragen_von_hand(treasury):
    treasury.setze_anker(5.0, bereits_heute=None)

    assert not treasury.rechnet_selbst()
    assert treasury.aus_abrechnung(FesteAbrechnung(99.0)) is None
    assert treasury.state().balance_usd == pytest.approx(5.0)


def test_der_anker_setzt_den_stand_sofort(treasury):
    treasury.charge(1.0, "llm")

    treasury.setze_anker(1.11, bereits_heute=0.0)

    assert treasury.state().balance_usd == pytest.approx(1.11)


def test_das_nachfuehren_zaehlt_nicht_als_verdienst(treasury):
    """Sonst hielte er sich für selbsttragend, weil jemand Geld nachgelegt hat."""
    treasury.setze_anker(5.0, bereits_heute=0.0)

    treasury.aus_abrechnung(FesteAbrechnung(1.0))

    stand = treasury.state()
    assert stand.balance_usd == pytest.approx(4.0)
    assert stand.earned_usd == 0.0
    assert not stand.self_sustaining


def test_ein_negativer_verbrauch_erhoeht_das_guthaben_nicht(treasury):
    """Die Abrechnung zaehlt nur Kosten. Alles andere waere ein Fehler."""
    treasury.setze_anker(1.0, bereits_heute=0.0)

    treasury.aus_abrechnung(FesteAbrechnung(-10.0))

    assert treasury.state().balance_usd == pytest.approx(1.0)


def test_aufgeladenes_guthaben_sieht_er_nicht_von_allein(treasury):
    """Bekannte Grenze: Die Abrechnung kennt Kosten, keine Einzahlungen.

    Nach dem Aufladen muss der Stand einmal neu eingetragen werden -
    einmal pro Aufladung, nicht einmal pro Tag.
    """
    treasury.setze_anker(1.0, bereits_heute=0.0)
    abrechnung = FesteAbrechnung(0.5)
    treasury.aus_abrechnung(abrechnung)
    assert treasury.state().balance_usd == pytest.approx(0.5)

    # Der Betreiber laedt 10 USD auf - die Abrechnung meldet davon nichts.
    treasury.aus_abrechnung(abrechnung)
    assert treasury.state().balance_usd == pytest.approx(0.5)

    # Erst ein neuer Anker bringt es in Ordnung.
    treasury.setze_anker(10.5, bereits_heute=abrechnung.kosten)
    treasury.aus_abrechnung(abrechnung)
    assert treasury.state().balance_usd == pytest.approx(10.5)
