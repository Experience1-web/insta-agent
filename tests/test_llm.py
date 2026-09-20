"""Die Aufwandsstufe kennt nicht jedes Modell - ein falsch gesetzter
Parameter bricht den ganzen Zyklus ab."""

import pytest

from insta_agent.llm import unterstuetzt_effort


@pytest.mark.parametrize(
    "model",
    ["claude-opus-5", "claude-opus-4-8", "claude-sonnet-5", "claude-fable-5-1"],
)
def test_moderne_modelle_bekommen_die_aufwandsstufe(model):
    assert unterstuetzt_effort(model)


@pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5"])
def test_modelle_ohne_aufwandsstufe_bekommen_sie_nicht(model):
    """Genau hier brach der erste echte Lauf ab: Haiku lehnt mit 400 ab."""
    assert not unterstuetzt_effort(model)


def test_unbekanntes_modell_bekommt_sie_vorsichtshalber_nicht():
    """Weglassen heißt Voreinstellung. Falsch mitschicken heißt Abbruch."""
    assert not unterstuetzt_effort("claude-irgendwas-neues-7")


def test_die_gunstige_routine_nutzt_ein_modell_ohne_aufwandsstufe():
    """Der Standard muss zur Positivliste passen, sonst kracht es wieder."""
    from insta_agent.config import LLMConfig

    config = LLMConfig()
    assert not unterstuetzt_effort(config.cheap_model)
    assert unterstuetzt_effort(config.model)


# --- Modellwahl je Aufgabe ------------------------------------------------


class FakeTreasury:
    def __init__(self, modus):
        self._modus = modus

    def state(self):
        from types import SimpleNamespace

        return SimpleNamespace(mode=self._modus)


def _brain():
    from insta_agent.config import LLMConfig
    from insta_agent.economy.ledger import Mode
    from insta_agent.llm import Brain

    b = object.__new__(Brain)
    b.config = LLMConfig()
    b.treasury = FakeTreasury(Mode.NORMAL)
    return b


def test_die_recherche_nutzt_das_guenstigere_modell():
    """Websuche war der teuerste Schritt - Seiten lesen kann auch Sonnet."""
    b = _brain()
    assert b._model_for("research") == b.config.research_model
    assert b._model_for("research") != b.config.model


def test_entscheidungen_laufen_auf_dem_grossen_modell():
    b = _brain()
    assert b._model_for("reasoning") == b.config.model


def test_routine_laeuft_auf_dem_billigsten():
    b = _brain()
    assert b._model_for("routine") == b.config.cheap_model


def test_im_sparbetrieb_laeuft_alles_billig():
    from insta_agent.economy.ledger import Mode

    b = _brain()
    b.treasury = FakeTreasury(Mode.FRUGAL)
    for aufgabe in ("reasoning", "research", "routine"):
        assert b._model_for(aufgabe) == b.config.cheap_model


def test_die_recherche_denkt_weniger_tief():
    """Spart Denk-Token bei einem Schritt, der vor allem Lesen ist."""
    b = _brain()
    recherche = b._output_config(b.config.research_model, "research")
    denken = b._output_config(b.config.model, "reasoning")

    assert recherche == {"effort": "medium"}
    assert denken == {"effort": "high"}


# --- Meldungen der Websuche ----------------------------------------------


def test_die_erschoepfte_websuche_wird_auf_deutsch_erklaert():
    """Im Protokoll stand vorher nur "max_uses_exceeded"."""
    from insta_agent.llm import _suchfehler

    text = _suchfehler("max_uses_exceeded", None)
    assert "aufgebraucht" in text
    assert "max_uses" not in text


def test_ein_unbekannter_fehlercode_geht_nicht_verloren():
    from insta_agent.llm import _suchfehler

    assert "brandneu" in _suchfehler("brandneu", None)


def test_der_agent_erfaehrt_wie_viele_suchen_er_hat():
    """Sonst stellt er eine fünfte Anfrage, die verworfen wird."""
    import inspect

    from insta_agent.brain import research

    quelle = inspect.getsource(research.run_market_research)
    assert "{brain.suchbudget} Suchanfragen" in quelle


# --- Strukturierte Antwort mit Websuche -----------------------------------

from types import SimpleNamespace  # noqa: E402

from pydantic import BaseModel  # noqa: E402


class _Schema(BaseModel):
    wert: str


def _ANTWORT():
    return _Schema(wert="fertig")


@pytest.fixture
def brain():
    """Ein Brain mit echter Kasse, aber ohne echten Client."""
    from insta_agent.config import EconomyConfig
    from insta_agent.economy.ledger import Treasury
    from insta_agent.store import Store

    import tempfile
    from pathlib import Path as _P

    b = _brain()
    b.treasury = Treasury(Store(_P(tempfile.mkdtemp()) / "a.db"), EconomyConfig())
    b.letzte_quellen = []
    return b



def _bad_request(meldung: str):
    """Ein echter 400er des SDK, kein nachgebauter."""
    import httpx2 as httpx

    from anthropic import BadRequestError

    antwort = httpx.Response(
        400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    return BadRequestError(meldung, response=antwort, body=None)


class _Antwort:
    def __init__(self, ergebnis):
        self.usage = SimpleNamespace(
            input_tokens=10, output_tokens=5,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )
        self.stop_reason = "end_turn"
        self.parsed_output = ergebnis
        self.content = []


def test_wenn_die_websuche_nicht_angenommen_wird_geht_es_ohne_sie_weiter(brain):
    """Ein Urteil ohne Nachschlagen ist besser als gar keins."""
    versuche = []

    def parse(**kwargs):
        versuche.append("tools" in kwargs)
        if "tools" in kwargs:
            raise _bad_request("tools are not supported with output_format")
        return _Antwort(_ANTWORT())

    brain.client = SimpleNamespace(messages=SimpleNamespace(parse=parse))

    ergebnis = brain.structured(
        schema=_Schema, system="s", prompt="p", label="Probe", web_search=True
    )

    assert ergebnis is not None
    assert versuche == [True, False], "erst mit Suche, dann ohne"


def test_ein_anderer_fehler_wird_nicht_verschluckt(brain):
    """Nur die Werkzeuge sind der Verdacht - alles andere gehoert nach oben."""
    def parse(**kwargs):
        raise _bad_request("credit balance is too low")

    brain.client = SimpleNamespace(messages=SimpleNamespace(parse=parse))

    from anthropic import BadRequestError

    with pytest.raises(BadRequestError, match="credit balance"):
        brain.structured(schema=_Schema, system="s", prompt="p", label="Probe")
