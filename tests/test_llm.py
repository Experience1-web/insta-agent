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
