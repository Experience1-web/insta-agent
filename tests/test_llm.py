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
