"""Vier Rollen, vier Aufträge - und wer mit welchem Modell arbeitet.

Die Trennung ist der ganze Sinn: Wer sucht, schreibt nicht. Wer schreibt,
prüft nicht. Wer prüft, gestaltet nicht. Und welches Modell eine Rolle
bekommt, gehört dem Betreiber in die Hand, nicht in den Quelltext.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from insta_agent.config import Settings
from insta_agent.mannschaft import (
    KEY_MODELLWAHL,
    NACH_SCHLUESSEL,
    ROLLEN,
    aufstellung,
    modell_fuer,
    standardmodell,
)
from test_cycle import _identitaet


@pytest.fixture
def einstellungen():
    return Settings()


@pytest.fixture
def settings(tmp_path):
    """Ein Agent mit eigenem Ordner, damit Tests sich nicht ins Gehege kommen."""
    return Settings(
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )


# --- Die Aufstellung -------------------------------------------------------


def test_alle_rollen_haben_einen_eigenen_auftrag():
    auftraege = [r.aufgabe for r in ROLLEN if r.schluessel != "chef"]

    assert len(ROLLEN) == 4
    assert len(set(auftraege)) == len(auftraege)
    assert len({r.name for r in ROLLEN if r.name}) == 3


def test_ohne_identitaet_fehlt_der_chef(einstellungen):
    """Solange er sich nicht erfunden hat, gibt es ihn nicht."""
    leute = aufstellung(None, einstellungen)

    assert "chef" not in [m["schluessel"] for m in leute]
    assert len(leute) == len(ROLLEN) - 1


def test_der_chef_bringt_namen_und_motto_aus_seiner_identitaet(einstellungen):
    i = _identitaet()

    chef = aufstellung(i, einstellungen)[0]

    assert chef["schluessel"] == "chef"
    assert chef["name"] == i.agent_name
    assert chef["aufgabe"] == i.motto


def test_jede_rolle_hat_stichworte(einstellungen):
    for m in aufstellung(_identitaet(), einstellungen):
        assert 3 <= len(m["eigenschaften"]) <= 5, m["schluessel"]


def test_eine_abgeschaltete_rolle_wird_als_solche_gezeigt(einstellungen):
    """Sonst sieht es aus, als würde geprüft, obwohl niemand hinsieht."""
    einstellungen.posting.pruefung_noetig = False

    leute = {m["schluessel"]: m for m in aufstellung(_identitaet(), einstellungen)}

    assert leute["pruefung"]["aktiv"] is False
    assert leute["bildsprache"]["aktiv"] is True


# --- Die Modellwahl --------------------------------------------------------


def test_pruefen_und_gestalten_laufen_nicht_auf_dem_teuersten_modell(einstellungen):
    """Alles drei ist Nachschlagen und Vergleichen, keine kreative Arbeit."""
    leute = {m["schluessel"]: m for m in aufstellung(_identitaet(), einstellungen)}

    assert leute["chef"]["modell"] == einstellungen.llm.model
    assert leute["pruefung"]["modell"] == einstellungen.llm.research_model
    assert leute["bildsprache"]["modell"] == einstellungen.llm.research_model
    assert leute["stoff"]["modell"] == einstellungen.llm.research_model


def test_die_wahl_des_betreibers_sticht_die_voreinstellung(einstellungen):
    wahl = {"pruefung": "claude-haiku-4-5"}

    assert modell_fuer("pruefung", wahl, einstellungen.llm) == "claude-haiku-4-5"
    # Die anderen bleiben, wie sie waren.
    assert modell_fuer("chef", wahl, einstellungen.llm) == einstellungen.llm.model


def test_ohne_wahl_gilt_die_voreinstellung(einstellungen):
    for rolle in ROLLEN:
        assert modell_fuer(rolle.schluessel, {}, einstellungen.llm) == standardmodell(
            rolle, einstellungen.llm
        )


def test_der_sparbetrieb_sticht_die_wahl(treasury, store):
    """Wenn das Geld knapp wird, ist die Bremse wichtiger als der Wunsch."""
    from insta_agent.config import LLMConfig
    from insta_agent.economy.ledger import Mode
    from insta_agent.llm import Brain

    brain = Brain.__new__(Brain)
    brain.config = LLMConfig()
    brain.treasury = treasury

    assert brain._model_for("research", "claude-opus-5") == "claude-opus-5"

    treasury.charge(9.5, "llm")  # unter low_balance
    assert treasury.state().mode is Mode.FRUGAL
    assert brain._model_for("research", "claude-opus-5") == brain.config.cheap_model


# --- Über die Oberfläche umstellen ----------------------------------------


def _server(settings):
    from insta_agent.web import Steuerung, _handler_klasse

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(Steuerung(settings), None))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _post(port: int, pfad: str, rumpf: dict):
    anfrage = urllib.request.Request(
        f"http://127.0.0.1:{port}{pfad}",
        data=json.dumps(rumpf).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(anfrage, timeout=5) as antwort:
        return json.loads(antwort.read())


def test_das_modell_laesst_sich_ueber_die_oberflaeche_umstellen(settings):
    from insta_agent.runner import Agent

    server, port = _server(settings)
    try:
        assert _post(port, "/api/modell", {"wer": "pruefung", "modell": "claude-haiku-4-5"})["ok"]

        agent = Agent(settings)
        try:
            assert agent.store.get_json(KEY_MODELLWAHL) == {"pruefung": "claude-haiku-4-5"}
            assert agent._modell("pruefung") == "claude-haiku-4-5"
            assert agent._modell("chef") is None
        finally:
            agent.close()
    finally:
        server.shutdown()
        server.server_close()


def test_eine_leere_wahl_setzt_auf_die_voreinstellung_zurueck(settings):
    from insta_agent.runner import Agent

    server, port = _server(settings)
    try:
        _post(port, "/api/modell", {"wer": "pruefung", "modell": "claude-haiku-4-5"})
        _post(port, "/api/modell", {"wer": "pruefung", "modell": ""})

        agent = Agent(settings)
        try:
            assert agent._modell("pruefung") is None
        finally:
            agent.close()
    finally:
        server.shutdown()
        server.server_close()


def test_ein_unbekanntes_modell_wird_abgelehnt(settings):
    """Ohne hinterlegten Preis koennte die Kasse nicht mehr mitrechnen."""
    server, port = _server(settings)
    try:
        with pytest.raises(urllib.error.HTTPError) as fehler:
            _post(port, "/api/modell", {"wer": "pruefung", "modell": "gpt-irgendwas"})
        assert fehler.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_eine_unbekannte_rolle_wird_abgelehnt(settings):
    server, port = _server(settings)
    try:
        with pytest.raises(urllib.error.HTTPError) as fehler:
            _post(port, "/api/modell", {"wer": "hausmeister", "modell": "claude-opus-5"})
        assert fehler.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_vom_handy_aus_laesst_sich_nichts_umstellen(settings):
    from insta_agent.web import Steuerung, _handler_klasse

    steuerung = Steuerung(settings, nur_lesen=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(steuerung, None))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as fehler:
            _post(port, "/api/modell", {"wer": "pruefung", "modell": "claude-opus-5"})
        assert fehler.value.code == 409
    finally:
        server.shutdown()
        server.server_close()


# --- Porträts --------------------------------------------------------------


def test_jede_rolle_weiss_wie_sie_aussehen_will():
    from insta_agent.imaging.portraits import portraitwunsch

    for rolle in ROLLEN:
        wunsch = portraitwunsch(rolle)
        assert len(wunsch) > 80, rolle.schluessel
        # Ein gemeinsamer Stil, damit die drei nach einer Hand aussehen.
        assert "no text" in wunsch and "single person" in wunsch


def test_der_chef_bekommt_die_bildsprache_des_accounts_mit():
    from insta_agent.imaging.portraits import portraitwunsch

    i = _identitaet()
    wunsch = portraitwunsch(NACH_SCHLUESSEL["chef"], i)

    assert i.visual_identity in wunsch


def test_ohne_bilddienst_gibt_es_kein_portrait(tmp_path):
    """Und das ist kein Fehler - es bleibt beim gezeichneten Zeichen."""
    from insta_agent.imaging.portraits import erzeuge_portrait

    assert erzeuge_portrait(None, NACH_SCHLUESSEL["pruefung"], tmp_path / "x.png") is None


def test_ein_streikender_bilddienst_haelt_nichts_auf(tmp_path):
    from insta_agent.imaging.portraits import erzeuge_portrait

    class KaputterDienst:
        def erzeuge(self, prompt, ziel):
            raise RuntimeError("Tageslimit erreicht")

    assert erzeuge_portrait(KaputterDienst(), ROLLEN[0], tmp_path / "x.png") is None


def test_jede_rolle_hat_ihren_eigenen_platz(tmp_path):
    """Sonst überschreibt das zweite Porträt das erste."""
    from insta_agent.imaging.portraits import portraitpfad

    pfade = {portraitpfad(tmp_path, r.schluessel) for r in ROLLEN}

    assert len(pfade) == len(ROLLEN)
