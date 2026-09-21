"""Die Mannschaft lässt sich umschreiben - und zwar nicht nur zum Schein.

Ein Name, den der Betreiber im Dashboard ändert, muss dort ankommen, wo
die Person arbeitet. Sonst denkt und unterschreibt sie weiter unter dem
alten Namen, und das Dashboard zeigt eine Beschriftung, hinter der nichts
steht.

Dasselbe gilt für die Haltung: Was der Betreiber jemandem mitgibt, geht
in die Anweisung ein. Nur eines geht nicht, und das ist der Punkt, an dem
diese Freiheit endet: Niemand kann anordnen, dass eine falsche Zahl
durchgewunken wird.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from insta_agent.mannschaft import KEY_MANNSCHAFT, aufstellung, person
from test_cycle import (  # noqa: F401 - agent und settings sind Fixtures
    FakeBrain,
    _identitaet,
    agent,
    settings,
)


def _post(port: int, pfad: str, rumpf: dict):
    anfrage = urllib.request.Request(
        f"http://127.0.0.1:{port}{pfad}",
        data=json.dumps(rumpf).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(anfrage, timeout=5) as antwort:
        return json.loads(antwort.read())


def _server(settings, nur_lesen=False):
    from insta_agent.web import Steuerung, _handler_klasse

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_klasse(Steuerung(settings, nur_lesen=nur_lesen), None)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# --- Was der Betreiber ändert ----------------------------------------------


def test_die_voreinstellung_bleibt_wo_nichts_geaendert_wurde():
    eigen = person("pruefung", {"pruefung": {"name": "Ada Berg"}})

    assert eigen["name"] == "Ada Berg"
    assert eigen["rolle"] == "Endprüfung"
    assert len(eigen["eigenschaften"]) >= 3
    assert "portrait" in eigen["bildwunsch"]


def test_der_chef_holt_namen_und_motto_aus_seiner_identitaet():
    i = _identitaet()

    eigen = person("chef", {}, i)

    assert eigen["name"] == i.agent_name
    assert eigen["aufgabe"] == i.motto


def test_die_aufstellung_zeigt_die_aenderung(settings):
    leute = {
        m["schluessel"]: m
        for m in aufstellung(
            _identitaet(), settings, None, {"stoff": {"name": "Malik Frei", "haltung": "Knapp."}}
        )
    }

    assert leute["stoff"]["name"] == "Malik Frei"
    assert leute["stoff"]["haltung"] == "Knapp."


# --- Und ob es ankommt, wo gearbeitet wird ---------------------------------


def test_ein_neuer_name_steht_wirklich_in_der_anweisung():
    """Sonst denkt und unterschreibt sie weiter als Ruth Kellner."""
    from insta_agent.brain.pruefung import PRUEFER_NAME, pruefer_persona

    text = pruefer_persona("Ada Berg")

    assert "Ada Berg" in text
    assert PRUEFER_NAME not in text


def test_die_haltung_haengt_hinten_an_und_bleibt_begrenzt():
    from insta_agent.brain.gestaltung import gestalter_persona

    text = gestalter_persona("Jo Brandes", "Mag harte Schatten. Hasst Symmetrie.")

    assert "Mag harte Schatten" in text
    # Der Satz, der die Grenze zieht - ohne ihn wäre das Feld ein Hebel,
    # mit dem sich jede Kontrolle abschalten ließe.
    assert "erfinden, beschönigen" in text


def test_ohne_haltung_bleibt_die_anweisung_unveraendert():
    from insta_agent.brain.stoff import STOFF_PERSONA, stoff_persona

    assert stoff_persona() == STOFF_PERSONA


def test_der_pruefbericht_traegt_den_neuen_namen(agent):
    agent.store.set_json(KEY_MANNSCHAFT, {"pruefung": {"name": "Ada Berg"}})

    agent.run_cycle()

    from insta_agent.models import Pruefbericht

    zeile = agent.store.pending_drafts()[0]
    bericht = Pruefbericht.model_validate(json.loads(zeile["pruefung_json"]))
    assert bericht.geprueft_von == "Ada Berg"


def test_der_fund_traegt_den_neuen_namen(agent):
    agent.store.set_json(KEY_MANNSCHAFT, {"stoff": {"name": "Malik Frei"}})

    agent.run_cycle()

    fund = json.loads(agent.store.pending_drafts()[0]["fund_json"])
    assert fund["gesucht_von"] == "Malik Frei"


# --- Über die Oberfläche ----------------------------------------------------


def test_der_steckbrief_laesst_sich_ueber_das_dashboard_aendern(settings, monkeypatch):
    from insta_agent.runner import Agent

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    try:
        a.run_cycle()
    finally:
        a.close()

    server, port = _server(settings)
    try:
        antwort = _post(
            port,
            "/api/person",
            {
                "wer": "bildsprache",
                "felder": {
                    "name": "Kim Sarow",
                    "haltung": "Mag harte Schatten.",
                    "eigenschaften": ["a", "b", "c", "d", "e", "f", "g"],
                },
            },
        )
    finally:
        server.shutdown()
        server.server_close()

    assert antwort["ok"] is True
    assert antwort["person"]["name"] == "Kim Sarow"
    # Fünf Stichworte sind ein Steckbrief, zehn sind ein Lebenslauf.
    assert len(antwort["person"]["eigenschaften"]) == 5

    a = Agent(settings)
    try:
        assert a._person("bildsprache")["haltung"] == "Mag harte Schatten."
    finally:
        a.close()


def test_beim_chef_wandert_der_name_in_die_identitaet(settings, monkeypatch):
    """Zwei Wahrheiten nebeneinander wären eine zu viel."""
    from insta_agent.runner import Agent

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    try:
        a.run_cycle()
    finally:
        a.close()

    server, port = _server(settings)
    try:
        _post(port, "/api/person", {"wer": "chef", "felder": {"name": "Jona Vehl"}})
    finally:
        server.shutdown()
        server.server_close()

    a = Agent(settings)
    try:
        assert a.identity.agent_name == "Jona Vehl"
        assert a._person("chef")["name"] == "Jona Vehl"
    finally:
        a.close()


def test_das_aussehen_sticht_die_voreinstellung():
    from insta_agent.imaging.portraits import portraitwunsch
    from insta_agent.mannschaft import NACH_SCHLUESSEL

    wunsch = portraitwunsch(
        NACH_SCHLUESSEL["chef"], None, "a portrait of a man in his fifties, grey beard"
    )

    assert wunsch.startswith("a portrait of a man in his fifties")
    # Der gemeinsame Stil bleibt, sonst fallen die Porträts auseinander.
    assert "single person" in wunsch


def test_eine_unbekannte_rolle_wird_abgelehnt(settings):
    server, port = _server(settings)
    try:
        with pytest.raises(urllib.error.HTTPError) as fehler:
            _post(port, "/api/person", {"wer": "hausmeister", "felder": {"name": "X"}})
        assert fehler.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_vom_handy_aus_wird_nichts_umgeschrieben(settings):
    server, port = _server(settings, nur_lesen=True)
    try:
        for pfad in ("/api/person", "/api/portraitneu"):
            with pytest.raises(urllib.error.HTTPError) as fehler:
                _post(port, pfad, {"wer": "pruefung", "felder": {"name": "X"}})
            assert fehler.value.code == 409
    finally:
        server.shutdown()
        server.server_close()


def test_ohne_bilddienst_gibt_es_kein_neues_portrait(agent):
    agent.bildgenerator = None

    ergebnis = agent.male_portrait_neu("pruefung")

    assert ergebnis["ok"] is False
    assert "Bilddienst" in ergebnis["grund"]


# --- Das vorgegebene Profil ------------------------------------------------
#
# Zweimal hat er sich selbst eine Nische gesucht, zweimal hat er sich auf
# ein Gebiet festgelegt. Jetzt steht das Profil fest - und muss sich
# trotzdem ohne Quelltext ändern lassen.


def test_der_erste_lauf_uebernimmt_das_vorgegebene_profil(agent):
    from insta_agent.vorgabe import vorgegebene_identitaet

    agent.bootstrap()

    assert agent.identity.handle == vorgegebene_identitaet().handle
    # Und zwar ohne Marktrecherche - die ist damit gespart.
    assert "Marktrecherche" not in agent.brain.aufrufe


def test_die_nische_nennt_kein_einzelnes_fach():
    """Das Kriterium ist die Nische, nicht das Gebiet."""
    from insta_agent.vorgabe import vorgegebene_identitaet

    i = vorgegebene_identitaet()

    alles = (i.niche + " " + " ".join(i.content_pillars)).lower()
    # Fünf Felder, kein einzelnes - sonst ist es wieder eine Sparte.
    for gebiet in ("archäolog", "ki", "art", "weltall", "kurios"):
        assert gebiet in alles, gebiet
    assert len(i.content_pillars) == 5
    assert "niemals" in i.niche.lower() or "nicht auf ein" in i.niche.lower()


def test_wer_will_laesst_ihn_weiter_selbst_suchen(agent, monkeypatch):
    from test_cycle import _identitaet

    agent.settings.posting.identitaet_frei = True
    monkeypatch.setattr("insta_agent.runner.invent_identity", lambda *a, **k: _identitaet())

    agent.bootstrap()

    assert agent.identity.handle == _identitaet().handle


def test_die_nische_laesst_sich_im_dashboard_aendern(settings, monkeypatch):
    """Sonst wäre ein festes Profil eine Sackgasse."""
    from insta_agent.runner import Agent

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    try:
        a.bootstrap()
    finally:
        a.close()

    server, port = _server(settings)
    try:
        antwort = _post(
            port,
            "/api/person",
            {
                "wer": "chef",
                "felder": {
                    "niche": "Nur noch Weltraum",
                    "content_pillars": ["Sonden", "Planeten", "Messwerte"],
                    "bio": "Kurz und knapp.",
                },
            },
        )
    finally:
        server.shutdown()
        server.server_close()

    assert antwort["ok"] is True
    a = Agent(settings)
    try:
        assert a.identity.niche == "Nur noch Weltraum"
        assert a.identity.content_pillars == ["Sonden", "Planeten", "Messwerte"]
        assert a.identity.bio == "Kurz und knapp."
    finally:
        a.close()


def test_zu_wenige_saeulen_werden_nicht_uebernommen(settings, monkeypatch):
    """Unter drei lässt das Schema nicht zu - das darf nicht durchschlagen."""
    from insta_agent.runner import Agent

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    try:
        a.bootstrap()
        vorher = list(a.identity.content_pillars)
        a.aendere_person("chef", {"content_pillars": ["Nur eine"]})
        assert a.identity.content_pillars == vorher
    finally:
        a.close()
