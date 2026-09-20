"""Die Endprüfung ist die einzige Kontrolle vor der Freigabe.

Sie muss deshalb selbst streng geprüft sein: Was sie an das Modell
schickt, was sie mit der Antwort macht, und vor allem, was passiert,
wenn sie ausfällt. Eine Prüfung, die still scheitert und den Beitrag
trotzdem durchwinkt, ist schlimmer als gar keine.
"""

from __future__ import annotations

import pytest

from insta_agent.brain.pruefung import (
    PRUEFER_NAME,
    PRUEFER_PERSONA,
    _zu_pruefen,
    pruefe_beitrag,
)
from insta_agent.models import Befund, Pruefbericht
from test_cycle import _entwurf, _identitaet


class FakeBrain:
    """Merkt sich den Aufruf und gibt einen vorbereiteten Bericht zurück."""

    def __init__(self, bericht: Pruefbericht | None = None, quellen: list[str] | None = None):
        self.bericht = bericht or Pruefbericht(urteil="freigabe", zusammenfassung="ok")
        self.letzte_quellen = quellen or []
        self.aufruf: dict = {}
        self.suchbudget = 5

    def structured(self, **kwargs):
        self.aufruf = kwargs
        return self.bericht


def _pruefe(brain, **kwargs):
    return pruefe_beitrag(brain, identity=_identitaet(), draft=_entwurf(), **kwargs)


# --- Was geprüft wird ------------------------------------------------------


def test_alles_mit_tatsachen_geht_mit(draft):
    """Bild, Unterschrift und erster Kommentar - überall kann eine Zahl stehen."""
    text = _zu_pruefen(draft)

    assert draft.bildtext in text
    assert draft.caption in text
    assert draft.first_comment_prompt in text


def test_der_bildprompt_geht_nicht_mit(draft):
    """Der ist eine Malanweisung, keine Behauptung über die Welt."""
    assert draft.image_generation_prompt not in _zu_pruefen(draft)


def test_hashtags_gehen_nicht_mit(draft):
    """Prüfbar ist, was behauptet wird - nicht, wie es gefunden wird."""
    draft.hashtags = ["unbelegbarestichwort"]

    assert "unbelegbarestichwort" not in _zu_pruefen(draft)


# --- Wer prüft, mit welchem Modell -----------------------------------------


def test_geprueft_wird_mit_dem_recherchemodell():
    """Prüfen ist Nachschlagen, keine kreative Arbeit - das teuerste Modell
    waere hier verschwendet."""
    brain = FakeBrain()

    _pruefe(brain)

    assert brain.aufruf["task"] == "research"


def test_die_pruefung_darf_nachschlagen():
    brain = FakeBrain()

    _pruefe(brain, mit_suche=True)

    assert brain.aufruf["web_search"] is True


def test_die_pruefung_hat_einen_eigenen_auftrag():
    """Wer den Beitrag geschrieben hat, ist der falsche, um ihn zu pruefen."""
    brain = FakeBrain()

    _pruefe(brain)

    from insta_agent.brain.prompts import PERSONA

    assert brain.aufruf["system"] != PERSONA
    assert brain.aufruf["system"] == PRUEFER_PERSONA
    assert PRUEFER_NAME in brain.aufruf["system"]


# --- Was mit der Antwort passiert -------------------------------------------


def test_der_pruefer_wird_vom_code_eingetragen_nicht_vom_modell():
    """Sonst koennte sich das Modell selbst ein schoeneres Zeugnis ausstellen."""
    brain = FakeBrain(
        Pruefbericht(urteil="freigabe", zusammenfassung="ok", geprueft_von="Der Chef persoenlich")
    )

    bericht = _pruefe(brain)

    assert bericht.geprueft_von == PRUEFER_NAME


def test_ob_gesucht_wurde_traegt_der_code_ein():
    """Das Modell darf nicht behaupten, es haette nachgeschlagen."""
    brain = FakeBrain(Pruefbericht(urteil="freigabe", zusammenfassung="ok", mit_suche=True))

    bericht = _pruefe(brain, mit_suche=False)

    assert bericht.mit_suche is False


def test_die_wirklich_aufgerufenen_quellen_kommen_dazu():
    brain = FakeBrain(
        Pruefbericht(urteil="freigabe", zusammenfassung="ok", quellen=["https://a.test"]),
        quellen=["https://b.test", "https://a.test"],
    )

    bericht = _pruefe(brain)

    assert bericht.quellen == ["https://a.test", "https://b.test"]


# --- Das Urteil -------------------------------------------------------------


def test_nur_freigabe_darf_raus():
    for urteil in ("nachbessern", "ablehnen"):
        bericht = Pruefbericht(urteil=urteil, zusammenfassung="x")
        assert not bericht.darf_raus
    assert Pruefbericht(urteil="freigabe", zusammenfassung="x").darf_raus


def test_beanstandet_zaehlt_alles_ausser_belegt():
    """Unbelegbar ist kein mildes Urteil - eine Zahl ohne Quelle zaehlt mit."""
    bericht = Pruefbericht(
        urteil="nachbessern",
        zusammenfassung="x",
        befunde=[
            Befund(behauptung="a", urteil="belegt", begruendung="-"),
            Befund(behauptung="b", urteil="unbelegbar", begruendung="-"),
            Befund(behauptung="c", urteil="ungenau", begruendung="-"),
            Befund(behauptung="d", urteil="falsch", begruendung="-"),
        ],
    )

    assert [b.behauptung for b in bericht.beanstandet] == ["b", "c", "d"]


# --- Im Zyklus --------------------------------------------------------------


def test_der_bericht_haengt_am_entwurf(agent_mit_doppel):
    """Sonst sieht der Betreiber bei der Freigabe nicht, was gefunden wurde."""
    import json

    agent = agent_mit_doppel
    agent.run_cycle()

    zeile = agent.store.pending_drafts()[0]
    bericht = json.loads(zeile["pruefung_json"])

    assert bericht["urteil"] == "freigabe"
    assert bericht["geprueft_von"] == PRUEFER_NAME


def test_ein_ausfall_der_pruefung_kostet_nicht_den_zyklus(agent_mit_doppel, monkeypatch):
    """Ein fehlender Bericht ist schlecht. Ein verlorener Tag ist schlimmer."""
    agent = agent_mit_doppel
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Suche kaputt")),
    )

    bericht = agent.run_cycle()

    assert bericht.halted_reason is None
    assert len(agent.store.pending_drafts()) == 1
    assert any("nicht geprüft" in s for s in bericht.steps)


def test_ein_ausfall_wird_nicht_als_geprueft_ausgegeben(agent_mit_doppel, monkeypatch):
    agent = agent_mit_doppel
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Suche kaputt")),
    )

    agent.run_cycle()

    assert agent.store.pending_drafts()[0]["pruefung_json"] is None


def test_im_autopilot_haelt_ein_schlechtes_urteil_den_beitrag_an(
    agent_mit_doppel, monkeypatch
):
    """Genau dafür ist die Prüfung da: Wo kein Mensch mehr hinsieht,
    entscheidet sie."""
    agent = agent_mit_doppel
    agent.settings.posting.freigabe_noetig = False
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: Pruefbericht(
            urteil="ablehnen",
            zusammenfassung="Die Zahl steht so nirgends.",
            befunde=[Befund(behauptung="25 Tage", urteil="falsch", begruendung="-")],
        ),
    )

    bericht = agent.run_cycle()

    assert agent.store.approved_drafts() == []
    assert any("angehalten" in s for s in bericht.steps)


def test_im_autopilot_geht_ein_sauberer_beitrag_weiter_raus(agent_mit_doppel):
    agent = agent_mit_doppel
    agent.settings.posting.freigabe_noetig = False

    agent.run_cycle()

    assert len(agent.store.approved_drafts()) == 1


def test_ohne_pruefung_laeuft_alles_wie_vorher(agent_mit_doppel):
    """Abschaltbar bleibt sie - aber nur ausdruecklich."""
    agent = agent_mit_doppel
    agent.settings.posting.pruefung_noetig = False

    agent.run_cycle()

    assert agent.store.pending_drafts()[0]["pruefung_json"] is None


@pytest.fixture
def draft():
    return _entwurf()


@pytest.fixture
def agent_mit_doppel(tmp_path, monkeypatch):
    """Ein vollständiger Agent, dessen Modellaufrufe von Doppeln bedient werden."""
    from insta_agent.config import EconomyConfig, LLMConfig, PostingConfig, Settings
    from insta_agent.runner import Agent
    from test_cycle import FakeBrain

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    settings = Settings(
        llm=LLMConfig(),
        economy=EconomyConfig(
            treasury_start_usd=5.0,
            low_balance_usd=1.0,
            halt_balance_usd=0.25,
            max_cost_per_cycle_usd=2.0,
        ),
        posting=PostingConfig(posts_per_day=1, live=False),
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )
    a = Agent(settings)
    yield a
    a.close()
