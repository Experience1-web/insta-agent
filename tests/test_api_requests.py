"""Prüft die tatsächlich abgeschickten API-Anfragen auf Gültigkeit.

Zwei echte Läufe sind an Dingen gescheitert, die kein Test gesehen hat,
weil niemand nachsah, WAS eigentlich an die API geht. Dieser Test spielt
einen vollständigen Zyklus durch, zeichnet jede Anfrage auf und prüft sie
gegen die Regeln der einzelnen Modelle.
"""

from types import SimpleNamespace

import pytest

from insta_agent.config import EconomyConfig, PostingConfig, Settings
from insta_agent.llm import unterstuetzt_effort
from insta_agent.runner import Agent
from test_cycle import (
    _analyse,
    _entwurf,
    _geschaeftsplan,
    _gestaltungsurteil,
    _identitaet,
    _pruefbericht,
    _reflexion,
    _strategie,
)

ANTWORTEN = {
    "MarketAnalysis": _analyse,
    "Identity": _identitaet,
    "StrategyUpdate": _strategie,
    "PostDraft": _entwurf,
    "Reflection": _reflexion,
    "MonetizationPlan": _geschaeftsplan,
    "Pruefbericht": _pruefbericht,
    "Gestaltungsurteil": _gestaltungsurteil,
}


class AufzeichnenderClient:
    """Ein Anthropic-Client, der nichts sendet, sondern mitschreibt."""

    def __init__(self):
        self.anfragen: list[dict] = []
        self.messages = SimpleNamespace(parse=self._parse, create=self._create)

    @staticmethod
    def _usage():
        return SimpleNamespace(
            input_tokens=1200,
            output_tokens=400,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )

    def _parse(self, **kwargs):
        self.anfragen.append(kwargs)
        schema = kwargs["output_format"].__name__
        return SimpleNamespace(
            usage=self._usage(), stop_reason="end_turn", parsed_output=ANTWORTEN[schema]()
        )

    def _create(self, **kwargs):
        self.anfragen.append(kwargs)
        return SimpleNamespace(
            usage=self._usage(),
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="Kurzvideos wachsen.")],
        )


@pytest.fixture
def agent_mit_mitschrift(tmp_path, monkeypatch):
    client = AufzeichnenderClient()
    monkeypatch.setattr(
        "insta_agent.llm.anthropic.Anthropic", lambda *a, **k: client
    )
    settings = Settings(
        economy=EconomyConfig(treasury_start_usd=20.0, max_cost_per_cycle_usd=10.0),
        posting=PostingConfig(),
        db_path=tmp_path / "a.db",
        media_dir=tmp_path / "m",
        draft_dir=tmp_path / "d",
    )
    settings.anthropic_api_key = "sk-ant-test"
    agent = Agent(settings)
    yield agent, client
    agent.close()


def test_ein_vollstaendiger_zyklus_sendet_nur_gueltige_anfragen(agent_mit_mitschrift):
    agent, client = agent_mit_mitschrift
    bericht = agent.run_cycle()

    assert bericht.halted_reason is None, bericht.halted_reason
    assert client.anfragen, "es wurde überhaupt keine Anfrage gestellt"

    for anfrage in client.anfragen:
        model = anfrage["model"]

        # Genau hier brach der erste echte Lauf ab.
        if "output_config" in anfrage and "effort" in anfrage["output_config"]:
            assert unterstuetzt_effort(model), (
                f"{model} bekommt die Aufwandsstufe, kennt sie aber nicht"
            )

        assert anfrage["max_tokens"] > 0
        assert anfrage["messages"], "leere Nachrichtenliste"
        assert anfrage["system"], "ohne System-Prompt verliert er seine Haltung"


def test_der_zyklus_erzeugt_wirklich_ein_bild_und_einen_entwurf(agent_mit_mitschrift):
    """Bis zum Ende durchlaufen, nicht nur bis zum ersten Modellaufruf."""
    from pathlib import Path

    agent, _ = agent_mit_mitschrift
    bericht = agent.run_cycle()

    assert agent.identity is not None
    assert agent.strategy is not None
    assert len(bericht.drafts_written) == 1

    entwuerfe = agent.store.pending_drafts()
    assert len(entwuerfe) == 1
    bild = Path(entwuerfe[0]["image_path"])
    assert bild.exists() and bild.stat().st_size > 1000


def test_die_websuche_geht_an_das_guenstige_modell(agent_mit_mitschrift):
    agent, client = agent_mit_mitschrift
    agent.run_cycle()

    mit_suche = [a for a in client.anfragen if a.get("tools")]
    # Dreimal wird nachgeschlagen: Marktrecherche, Bildsprache, Endprüfung.
    # Alle drei gehen an das Recherchemodell, nicht an das teure.
    assert len(mit_suche) == 3, "Recherche, Bildsprache und Endprüfung suchen je einmal"
    for anfrage in mit_suche:
        assert anfrage["model"] == agent.settings.llm.research_model
        assert anfrage["tools"][0]["type"] == "web_search_20260209"


def test_jeder_aufruf_wird_auch_abgerechnet(agent_mit_mitschrift):
    """Sonst läuft die Budgetbremse ins Leere."""
    agent, client = agent_mit_mitschrift
    bericht = agent.run_cycle()

    buchungen = [z for z in agent.store.ledger_entries(100) if z["category"] == "llm"]
    assert len(buchungen) == len(client.anfragen)
    assert bericht.cost_usd > 0
