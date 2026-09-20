"""Ein Entwurf darf nie ungeprüft aussehen, ohne dass man etwas tun kann.

Der Fall aus dem Betrieb: Die Endprüfung beanstandet drei Sachen, die
Nachbesserung schreibt den Beitrag neu - und mitten in der zweiten
Prüfung ist das Zyklusbudget alle. Zurück bleibt ein frisch geschriebener
Entwurf ohne Bericht.

Im Dashboard sah das aus wie "nicht geprüft", also wie ein Entwurf, bei
dem die Prüfung abgeschaltet war. Der Knopf "Nachbessern" verschwand
dabei, weil es keinen Bericht mehr gab, an dem er hängen könnte. Übrig
blieben Freigeben und Verwerfen - und Freigeben ging scharf hinaus.

Also: Die Prüfung muss sich nachholen lassen, und der Abbruch muss im
Protokoll stehen.
"""

from __future__ import annotations

import json

import pytest

from insta_agent.economy.ledger import CycleBudgetExceeded
from insta_agent.models import Befund, Pruefbericht
from test_cycle import (  # noqa: F401 - agent und settings sind Fixtures
    FakeBrain,
    agent,
    settings,
)


def _beanstandet() -> Pruefbericht:
    return Pruefbericht(
        urteil="nachbessern",
        zusammenfassung="Drei Zahlen sind nirgends belegt.",
        befunde=[
            Befund(
                behauptung="7.902 Meter",
                urteil="unbelegbar",
                begruendung="Keine Fundstelle nennt diese Tiefe.",
            )
        ],
    )


def _entwurf_mit_befund(agent) -> int:
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    agent.store.set_pruefung(post_id, _beanstandet())
    return post_id


# --- Die Lücke selbst ------------------------------------------------------


def test_eine_abgebrochene_nachbesserung_bleibt_im_protokoll(agent, monkeypatch):
    """Sonst verschwindet der gefährlichste Zustand spurlos."""
    post_id = _entwurf_mit_befund(agent)

    # Das Geld geht genau dann aus, wenn der neue Text schon steht.
    def kein_geld_mehr(*a, **k):
        raise CycleBudgetExceeded("Zyklusbudget aufgebraucht: 1.53 USD von 1.50 USD.")

    monkeypatch.setattr(agent, "_pruefe", kein_geld_mehr)

    with pytest.raises(CycleBudgetExceeded):
        agent.nachbessern(post_id)

    # Der Entwurf steht neu geschrieben da - aber ohne Bericht.
    assert agent.store.get_post(post_id)["pruefung_json"] is None
    eintraege = [z["message"] for z in agent.store.recent_journal(10)]
    assert any("nicht mehr geprüft" in e for e in eintraege)


def test_die_pruefung_laesst_sich_nachholen(agent, monkeypatch):
    post_id = _entwurf_mit_befund(agent)
    monkeypatch.setattr(
        agent, "_pruefe", lambda *a, **k: (_ for _ in ()).throw(CycleBudgetExceeded("leer"))
    )
    with pytest.raises(CycleBudgetExceeded):
        agent.nachbessern(post_id)

    ergebnis = agent.pruefe_nach(post_id)

    assert ergebnis["ok"] is True
    assert ergebnis["urteil"] == "freigabe"
    assert agent.store.get_post(post_id)["pruefung_json"] is not None


# --- Die Regeln drumherum --------------------------------------------------


def test_was_schon_geprueft_ist_wird_nicht_zweimal_bezahlt(agent):
    post_id = _entwurf_mit_befund(agent)

    ergebnis = agent.pruefe_nach(post_id)

    assert ergebnis["ok"] is False
    assert "schon geprüft" in ergebnis["grund"]


def test_nur_entwuerfe_lassen_sich_pruefen(agent):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    agent.store.freigeben(post_id)

    assert agent.pruefe_nach(post_id)["ok"] is False


def test_ein_unbekannter_entwurf_wird_abgelehnt(agent):
    assert agent.pruefe_nach(9999)["ok"] is False


def test_auch_bei_abgeschalteter_pruefung_laesst_sich_nachholen(settings, monkeypatch):
    """Wer den Knopf drückt, will geprüft haben - das sticht die Einstellung."""
    from insta_agent.runner import Agent

    settings.posting.pruefung_noetig = False
    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    try:
        a.run_cycle()
        post_id = a.store.pending_drafts()[0]["id"]
        assert a.store.get_post(post_id)["pruefung_json"] is None

        ergebnis = a.pruefe_nach(post_id)

        assert ergebnis["ok"] is True
        assert a.store.get_post(post_id)["pruefung_json"] is not None
    finally:
        a.close()


def test_der_bericht_landet_auch_im_dashboard(settings, monkeypatch):
    from insta_agent.runner import Agent
    from insta_agent.web import Steuerung

    settings.posting.pruefung_noetig = False
    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    try:
        a.run_cycle()
        post_id = a.store.pending_drafts()[0]["id"]
        a.pruefe_nach(post_id)
    finally:
        a.close()

    entwurf = Steuerung(settings).zustand()["entwuerfe"][0]

    assert entwurf["pruefung"]["urteil"] == "freigabe"


def test_vom_handy_aus_wird_nicht_geprueft(settings):
    """Nur nachsehen heißt nur nachsehen - auch wenn es Geld kostet."""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from insta_agent.web import Steuerung, _handler_klasse

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_klasse(Steuerung(settings, nur_lesen=True), None)
    )
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        anfrage = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/pruefen",
            data=json.dumps({"id": 1}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as fehler:
            urllib.request.urlopen(anfrage, timeout=5)
        assert fehler.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
