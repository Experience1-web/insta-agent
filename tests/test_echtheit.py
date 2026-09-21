"""Die Endprüfung prüft nicht nur den Text, sondern den Fund selbst.

Erfunden wird nicht beim Schreiben, sondern beim Suchen. Eine erfundene
Art klingt genau wie eine echte, eine erfundene Expedition auch - und der
Text darüber kann vollkommen schlüssig sein. Wer nur den Text prüft,
prüft die falsche Stelle.

Dazu die zweite Sache, die hier hängt: Die Websuche gibt es in zwei
Fassungen, und die neuere kennt nicht jedes Modell. Schickt man sie an
eines, das sie nicht kennt, lehnt die Schnittstelle die ganze Anfrage ab -
der Aufruf läuft dann ohne Werkzeuge durch, und die Prüfung hat still
nichts nachgeschlagen.
"""

from __future__ import annotations

import pytest

from insta_agent.brain.pruefung import pruefe_beitrag
from insta_agent.llm import web_search_tool
from insta_agent.models import Pruefbericht
from test_cycle import (  # noqa: F401 - agent und settings sind Fixtures
    _entwurf,
    _fund,
    _identitaet,
    agent,
    settings,
)


class FakeBrain:
    def __init__(self):
        self.bericht = Pruefbericht(urteil="freigabe", zusammenfassung="ok")
        self.letzte_quellen: list[str] = []
        self.aufruf: dict = {}
        self.suchbudget = 5

    def structured(self, **kwargs):
        self.aufruf = kwargs
        return self.bericht


# --- Der Fund geht mit -----------------------------------------------------


def test_der_fund_liegt_der_pruefung_vor():
    brain = FakeBrain()

    pruefe_beitrag(brain, identity=_identitaet(), draft=_entwurf(), fund=_fund())

    prompt = brain.aufruf["prompt"]
    assert _fund().titel in prompt
    assert "Archäologisches Korrespondenzblatt 2026" in prompt


def test_die_echtheit_wird_ausdruecklich_verlangt():
    brain = FakeBrain()

    pruefe_beitrag(brain, identity=_identitaet(), draft=_entwurf(), fund=_fund())

    prompt = brain.aufruf["prompt"]
    assert "Gibt es diesen Fund überhaupt?" in prompt
    # Was es nicht gibt, laesst sich nicht nachbessern.
    assert '"ablehnen"' in prompt


def test_auch_die_beleglage_wird_geprueft():
    """Wer 'gesichert' schreibt und nur eine Pressemeldung hat, greift zu hoch."""
    brain = FakeBrain()

    pruefe_beitrag(brain, identity=_identitaet(), draft=_entwurf(), fund=_fund())

    assert "Beleglage richtig angegeben" in brain.aufruf["prompt"]


def test_ohne_fund_bleibt_der_auftrag_wie_er_war():
    """Sonst stuende dort ein Auftrag zu etwas, das gar nicht vorliegt."""
    brain = FakeBrain()

    pruefe_beitrag(brain, identity=_identitaet(), draft=_entwurf())

    assert "Gibt es diesen Fund überhaupt?" not in brain.aufruf["prompt"]


def test_im_zyklus_kommt_der_fund_bei_der_pruefung_an(agent):
    from insta_agent.models import Pruefbericht as PB

    gesehen = {}

    def merken(*a, **k):
        gesehen["fund"] = k.get("fund")
        return PB(urteil="freigabe", zusammenfassung="ok")

    import insta_agent.runner as runner

    alt = runner.pruefe_beitrag
    runner.pruefe_beitrag = merken
    try:
        agent.run_cycle()
    finally:
        runner.pruefe_beitrag = alt

    assert gesehen["fund"] is not None
    assert gesehen["fund"].titel == _fund().titel


# --- Die richtige Fassung der Websuche -------------------------------------


@pytest.mark.parametrize(
    "modell, erwartet",
    [
        ("claude-opus-5", "web_search_20260209"),
        ("claude-sonnet-5", "web_search_20260209"),
        ("claude-opus-4-8", "web_search_20260209"),
        # Haiku kennt die neuere Fassung nicht - mit ihr wuerde die ganze
        # Anfrage abgelehnt, und die Pruefung liefe ohne Nachschlagen.
        ("claude-haiku-4-5", "web_search_20250305"),
        ("", "web_search_20250305"),
    ],
)
def test_die_websuche_passt_zum_modell(modell, erwartet):
    assert web_search_tool(4, modell)["type"] == erwartet


def test_das_suchbudget_bleibt_in_beiden_fassungen(einstellungen=None):
    for modell in ("claude-sonnet-5", "claude-haiku-4-5"):
        assert web_search_tool(3, modell)["max_uses"] == 3
        assert web_search_tool(3, modell)["name"] == "web_search"


def test_die_pruefung_auf_haiku_sucht_trotzdem(settings, monkeypatch):
    """Der Betreiber darf das Modell umstellen, ohne die Suche zu verlieren."""
    from types import SimpleNamespace

    from insta_agent.config import LLMConfig
    from insta_agent.economy.ledger import Treasury
    from insta_agent.llm import Brain
    from insta_agent.store import Store

    anfragen = []

    class Mitschrift:
        def __init__(self):
            self.messages = SimpleNamespace(parse=self._parse, create=None)

        def _parse(self, **kwargs):
            anfragen.append(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=50,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                ),
                stop_reason="end_turn",
                parsed_output=Pruefbericht(urteil="freigabe", zusammenfassung="ok"),
                content=[],
            )

    monkeypatch.setattr("insta_agent.llm.anthropic.Anthropic", lambda *a, **k: Mitschrift())
    store = Store(settings.db_path)
    try:
        brain = Brain(LLMConfig(), Treasury(store, settings.economy), "sk-ant-test")
        pruefe_beitrag(
            brain,
            identity=_identitaet(),
            draft=_entwurf(),
            modell="claude-haiku-4-5",
            fund=_fund(),
        )
    finally:
        store.close()

    assert anfragen[0]["model"] == "claude-haiku-4-5"
    assert anfragen[0]["tools"][0]["type"] == "web_search_20250305"
