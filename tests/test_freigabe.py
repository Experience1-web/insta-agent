"""Nichts geht ohne das Ja des Betreibers nach draußen.

Der Agent schreibt eigenständig, aber veröffentlichen darf er nur, was
freigegeben wurde. Diese Prüfungen halten genau das fest - es ist die
Zusage, auf die sich der Betreiber verlässt.
"""

from __future__ import annotations

import pytest

from insta_agent.models import PostDraft, VisualSpec
from insta_agent.store import Store


def _entwurf(text: str = "Ein Beitrag") -> PostDraft:
    return PostDraft(
        pillar="Test",
        hook=text,
        caption=text,
        hashtags=["buero"],
        call_to_action="Speicher dir das.",
        visual=VisualSpec(headline=text),
        best_time_hint="morgens",
        expected_outcome="Speicherungen",
    )


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "agent.db")
    yield s
    s.close()


def test_neuer_entwurf_ist_nicht_freigegeben(store):
    post_id = store.add_draft(_entwurf(), None)
    assert store.approved_drafts() == []
    assert [z["id"] for z in store.pending_drafts()] == [post_id]


def test_freigabe_macht_den_entwurf_versandfertig(store):
    post_id = store.add_draft(_entwurf(), None)

    assert store.freigeben(post_id) is True
    assert [z["id"] for z in store.approved_drafts()] == [post_id]
    # Und er taucht nicht mehr als offener Entwurf auf.
    assert store.pending_drafts() == []


def test_verworfenes_geht_nie_raus(store):
    post_id = store.add_draft(_entwurf(), None)

    assert store.verwerfen(post_id) is True
    assert store.approved_drafts() == []
    assert store.pending_drafts() == []
    # Und es lässt sich auch nicht nachträglich doch noch freigeben.
    assert store.freigeben(post_id) is False


def test_veroeffentlichtes_laesst_sich_nicht_erneut_freigeben(store):
    """Sonst würde derselbe Beitrag ein zweites Mal hochgeladen."""
    post_id = store.add_draft(_entwurf(), None)
    store.freigeben(post_id)
    store.mark_published(post_id, "ig-123")

    assert store.freigeben(post_id) is False
    assert store.approved_drafts() == []


def test_zweimal_freigeben_aendert_nichts(store):
    """Ein Doppelklick auf den Knopf darf nichts doppelt in die Liste legen."""
    post_id = store.add_draft(_entwurf(), None)

    assert store.freigeben(post_id) is True
    assert store.freigeben(post_id) is False
    assert len(store.approved_drafts()) == 1


def test_freigabe_eines_unbekannten_beitrags_schlaegt_fehl(store):
    assert store.freigeben(9999) is False
    assert store.verwerfen(9999) is False


# --- Der Zyklus hält sich daran ------------------------------------------

from pathlib import Path  # noqa: E402

from insta_agent.config import EconomyConfig, LLMConfig, PostingConfig, Settings  # noqa: E402
from insta_agent.instagram.publisher import PublishResult  # noqa: E402
from insta_agent.runner import Agent  # noqa: E402
from tests.test_cycle import FakeBrain  # noqa: E402


class MitschreibenderVerlag:
    """Tut so, als ginge es raus - und merkt sich, was ihm gegeben wurde."""

    def __init__(self) -> None:
        self.veroeffentlicht: list[str] = []

    def publish(self, draft, image_path) -> PublishResult:
        self.veroeffentlicht.append(draft.caption)
        return PublishResult(published=True, ig_media_id=f"ig-{len(self.veroeffentlicht)}")


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    einstellungen = Settings(
        llm=LLMConfig(),
        economy=EconomyConfig(treasury_start_usd=5.0, max_cost_per_cycle_usd=2.0),
        posting=PostingConfig(posts_per_day=1, live=False),
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )
    a = Agent(einstellungen)
    a.publisher = MitschreibenderVerlag()
    yield a
    a.close()


def test_ein_zyklus_veroeffentlicht_nichts_von_allein(agent):
    """Das ist die Zusage: ohne Freigabe geht nichts raus."""
    agent.run_cycle()

    assert agent.publisher.veroeffentlicht == []
    assert len(agent.store.pending_drafts()) == 1


def test_erst_die_freigabe_laesst_den_beitrag_raus(agent):
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]
    agent.store.freigeben(entwurf["id"])

    agent.run_cycle()

    assert agent.publisher.veroeffentlicht == [entwurf["caption"]]
    zeile = agent.store.recent_posts(limit=10)
    veroeffentlicht = [z for z in zeile if z["status"] == "published"]
    assert len(veroeffentlicht) == 1
    assert veroeffentlicht[0]["ig_media_id"] == "ig-1"


def test_ein_freigegebener_beitrag_geht_nur_ein_einziges_mal_raus(agent):
    """Sonst stünde derselbe Beitrag zweimal im Profil."""
    agent.run_cycle()
    agent.store.freigeben(agent.store.pending_drafts()[0]["id"])

    agent.run_cycle()
    agent.run_cycle()

    assert len(agent.publisher.veroeffentlicht) == 1


def test_verworfenes_bleibt_auch_im_zyklus_drin(agent):
    agent.run_cycle()
    agent.store.verwerfen(agent.store.pending_drafts()[0]["id"])

    agent.run_cycle()

    assert agent.publisher.veroeffentlicht == []


def test_fehlendes_bild_haelt_den_beitrag_zurueck_statt_zu_stuerzen(agent):
    """Ein gelöschtes Bild darf nicht den ganzen Zyklus abbrechen."""
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]
    agent.store.freigeben(entwurf["id"])
    Path(entwurf["image_path"]).unlink()

    bericht = agent.run_cycle()

    assert agent.publisher.veroeffentlicht == []
    assert bericht.halted_reason is None
    assert any("Bild fehlt" in s for s in bericht.steps)


# --- Der Neuanfang räumt die alten Entwürfe weg ---------------------------


def test_neuanfang_verwirft_offene_entwuerfe(agent):
    """Sonst könnte ein Fehlklick sie unter dem neuen Profil hinausschicken."""
    agent.run_cycle()
    offen = agent.store.pending_drafts()
    assert len(offen) == 1

    agent.neu_erfinden()

    assert agent.store.pending_drafts() == []
    assert agent.store.approved_drafts() == []
    stati = [z["status"] for z in agent.store.recent_posts(limit=10)]
    assert stati == ["discarded"]


def test_neuanfang_verwirft_auch_schon_freigegebenes(agent):
    """Eine Freigabe aus der alten Nische gilt für die neue nicht mehr."""
    agent.run_cycle()
    agent.store.freigeben(agent.store.pending_drafts()[0]["id"])

    agent.neu_erfinden()
    agent.run_cycle()

    assert agent.publisher.veroeffentlicht == []


def test_neuanfang_laesst_veroeffentlichtes_in_ruhe(agent):
    """Was auf Instagram steht, bleibt seine Geschichte."""
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]
    agent.store.freigeben(entwurf["id"])
    agent.run_cycle()
    assert agent.store.published_count() == 1

    agent.neu_erfinden()

    assert agent.store.published_count() == 1
    veroeffentlicht = [z for z in agent.store.recent_posts(10) if z["status"] == "published"]
    assert veroeffentlicht[0]["ig_media_id"] == "ig-1"


# --- Autopilot ------------------------------------------------------------


def test_ohne_freigabepflicht_geht_der_beitrag_von_selbst_raus(agent):
    """Der Schalter für später: wenn die Beiträge verlässlich taugen."""
    agent.settings.posting.freigabe_noetig = False

    agent.run_cycle()
    assert agent.store.pending_drafts() == []
    assert len(agent.store.approved_drafts()) == 1

    agent.run_cycle()
    assert len(agent.publisher.veroeffentlicht) == 1


def test_die_freigabepflicht_ist_die_voreinstellung():
    """Niemand soll ungewollt in den Autopiloten rutschen."""
    from insta_agent.config import PostingConfig

    assert PostingConfig().freigabe_noetig is True


def test_der_autopilot_umgeht_das_verwerfen_nicht(agent):
    """Was der Betreiber verworfen hat, bleibt verworfen."""
    agent.run_cycle()
    agent.store.verwerfen(agent.store.pending_drafts()[0]["id"])

    agent.settings.posting.freigabe_noetig = False
    agent.run_cycle()

    # Nur der neue Beitrag geht raus, nicht der verworfene.
    assert len(agent.publisher.veroeffentlicht) == 0
    agent.run_cycle()
    assert len(agent.publisher.veroeffentlicht) == 1


# --- Veröffentlichen ohne Denkzyklus --------------------------------------


def test_veroeffentlichen_kostet_kein_guthaben(agent):
    """Hochladen ist kein Denken. Dafür einen Zyklus zu verlangen wäre absurd."""
    agent.run_cycle()
    agent.store.freigeben(agent.store.pending_drafts()[0]["id"])
    vorher = agent.treasury.state().spent_usd

    bericht = agent.veroeffentliche_jetzt()

    assert agent.publisher.veroeffentlicht != []
    assert agent.treasury.state().spent_usd == vorher
    assert bericht.finished_at is not None


def test_ohne_freigabe_geht_auch_sofort_nichts_raus(agent):
    agent.run_cycle()

    agent.veroeffentliche_jetzt()

    assert agent.publisher.veroeffentlicht == []


def test_zweimal_sofort_veroeffentlichen_postet_nicht_doppelt(agent):
    agent.run_cycle()
    agent.store.freigeben(agent.store.pending_drafts()[0]["id"])

    agent.veroeffentliche_jetzt()
    agent.veroeffentliche_jetzt()

    assert len(agent.publisher.veroeffentlicht) == 1


def test_die_freigabe_loest_das_veroeffentlichen_aus():
    """Das Ja des Betreibers ist der Ausloeser, nicht der naechste Zyklus."""
    from pathlib import Path

    quelle = (Path(__file__).resolve().parent.parent
              / "insta_agent" / "web.py").read_text("utf-8")
    assert "steuerung.jetzt_veroeffentlichen" in quelle
    assert 'wahl == "freigeben" and steuerung.settings.can_publish' in quelle
