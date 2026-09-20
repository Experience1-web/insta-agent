"""Der Umbau auf das Viralitäts-Format.

Geprüft wird, was schiefgehen kann: eine zu lange Hook-Zeile, ein alter
Entwurf ohne die neuen Felder, ein Neustart, der zu viel löscht.
"""

from __future__ import annotations

import json

import pytest

from insta_agent.brain.content import MAX_HOOK_WOERTER, _kuerze_auf_woerter
from insta_agent.imaging.renderer import FEED, STORY, render_post_image
from insta_agent.models import PostDraft, VisualSpec


def test_der_hook_wird_auf_sieben_woerter_gestutzt():
    """Sieben Wörter ist die Grenze aus der Vorlage - nicht verhandelbar."""
    lang = "Dieser eine Satz ist viel zu lang für ein Vorschaubild"
    gekuerzt = _kuerze_auf_woerter(lang, MAX_HOOK_WOERTER)

    assert len(gekuerzt.split()) == MAX_HOOK_WOERTER
    assert gekuerzt == "Dieser eine Satz ist viel zu lang"


def test_kurze_hooks_bleiben_unangetastet():
    kurz = "Dein Kalender ist kein Beweis."
    assert _kuerze_auf_woerter(kurz, MAX_HOOK_WOERTER) == kurz


def test_ein_alter_entwurf_ohne_die_neuen_felder_laedt_weiter():
    """In der Datenbank liegen Entwürfe von vor dem Umbau."""
    alt = {
        "pillar": "Alt",
        "hook": "Erste Zeile",
        "caption": "Der ganze Text",
        "hashtags": ["buero"],
        "call_to_action": "Speicher dir das",
        "visual": {"headline": "Alte Schlagzeile"},
        "best_time_hint": "morgens",
        "expected_outcome": "Speicherungen",
    }
    draft = PostDraft.model_validate(alt)

    assert draft.hook_text_on_screen == ""
    assert draft.image_generation_prompt == ""
    assert draft.first_comment_prompt == ""
    # Und er bekommt trotzdem einen Bildtext.
    assert draft.bildtext == "Alte Schlagzeile"


def test_der_bildtext_bevorzugt_den_hook():
    draft = PostDraft(
        pillar="x",
        hook_text_on_screen="Dein Kalender lügt.",
        hook="h",
        caption="c",
        hashtags=["a"],
        call_to_action="cta",
        visual=VisualSpec(headline="Etwas anderes"),
        best_time_hint="t",
        expected_outcome="e",
    )
    assert draft.bildtext == "Dein Kalender lügt."


@pytest.mark.parametrize("groesse,erwartet", [(STORY, (1080, 1920)), (FEED, (1080, 1350))])
def test_beide_bildformate_werden_erzeugt(tmp_path, groesse, erwartet):
    from PIL import Image

    spec = VisualSpec(headline="Dein Kalender ist kein Beweis.", footer="@probe")
    pfad = render_post_image(spec, tmp_path / "bild.png", groesse=groesse)

    assert Image.open(pfad).size == erwartet


def test_das_hochformat_ist_neunzehntel(tmp_path):
    """9:16 ist das Format, das Instagram für Reels erwartet."""
    breite, hoehe = STORY
    assert round(hoehe / breite, 3) == round(16 / 9, 3)


def test_neustart_loescht_die_entscheidungen_aber_nicht_die_kasse(tmp_path, monkeypatch):
    from insta_agent.config import EconomyConfig, LLMConfig, PostingConfig, Settings
    from insta_agent.runner import Agent
    from tests.test_cycle import FakeBrain

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    einstellungen = Settings(
        llm=LLMConfig(),
        economy=EconomyConfig(treasury_start_usd=5.0, max_cost_per_cycle_usd=2.0),
        posting=PostingConfig(posts_per_day=1, live=False),
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )
    agent = Agent(einstellungen)
    try:
        agent.run_cycle()
        assert agent.identity is not None
        kasse_vorher = agent.treasury.state().spent_usd
        beitraege_vorher = len(agent.store.recent_posts(limit=50))

        agent.neu_erfinden()

        assert agent.identity is None
        assert agent.strategy is None
        assert agent.analysis is None
        # Was Geld gekostet hat und was schon geschrieben wurde, bleibt.
        assert agent.treasury.state().spent_usd == kasse_vorher
        assert len(agent.store.recent_posts(limit=50)) == beitraege_vorher
    finally:
        agent.close()


def test_nach_dem_neustart_erfindet_er_sich_wirklich_neu(tmp_path, monkeypatch):
    from insta_agent.config import EconomyConfig, LLMConfig, PostingConfig, Settings
    from insta_agent.runner import Agent
    from tests.test_cycle import FakeBrain

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    einstellungen = Settings(
        llm=LLMConfig(),
        economy=EconomyConfig(treasury_start_usd=5.0, max_cost_per_cycle_usd=3.0),
        posting=PostingConfig(posts_per_day=1, live=False),
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )
    agent = Agent(einstellungen)
    try:
        agent.run_cycle()
        agent.neu_erfinden()
        agent.run_cycle()

        # Er hat wieder recherchiert und sich wieder ein Profil gegeben.
        assert agent.identity is not None
        assert agent.analysis is not None
        arten = [z["kind"] for z in agent.store.recent_journal(50)]
        assert arten.count("identity") >= 2
    finally:
        agent.close()


def test_die_seite_zeigt_bildprompt_und_ersten_kommentar():
    from pathlib import Path

    seite = (Path(__file__).resolve().parent.parent
             / "insta_agent" / "web_page.html").read_text("utf-8")
    # Der Prompt steckt im Popup, nicht mehr auf der Karte - sichtbar
    # bleiben muss er trotzdem.
    assert "Bild-Prompt" in seite
    assert "Erster Kommentar" in seite
    # Fremder Text darf nie ungeprüft in ein Attribut.
    assert 'data-text="${esc(p.bildprompt)}"' in seite
    assert 'data-text="${esc(p.erster_kommentar)}"' in seite


def test_die_rueckfrage_versteht_j_und_y():
    """Auf einem deutschen Rechner tippt man j, nicht y."""
    from insta_agent.cli import JA_WOERTER, NEIN_WOERTER

    for wort in ("j", "ja", "y", "yes", "J", "Ja"):
        assert wort.strip().lower() in JA_WOERTER
    for wort in ("n", "nein", "no", ""):
        assert wort.strip().lower() in NEIN_WOERTER
    # Kein Wort darf in beiden Mengen stehen.
    assert not (JA_WOERTER & NEIN_WOERTER)


def test_eine_leere_eingabe_bricht_ab():
    """Wer nur Enter drückt, soll nichts löschen."""
    from insta_agent.cli import JA_WOERTER, NEIN_WOERTER

    assert "" in NEIN_WOERTER
    assert "" not in JA_WOERTER


# --- Bildgetriebene Ausrichtung -------------------------------------------


def test_die_identitaet_verlangt_eine_bildgetriebene_nische():
    """Vorher stand dort "Du hast kein Fotostudio" - das trieb ihn zum Text."""
    import inspect

    from insta_agent.brain import identity

    quelle = inspect.getsource(identity.invent_identity)
    assert "das Bild trägt den Beitrag" in quelle
    assert "Ein einzelnes Bild muss das Thema tragen" in quelle
    # Die alte Einschränkung darf nicht zurückkommen.
    assert "Farbflächen, klare Typografie" not in quelle


def test_der_bildprompt_steht_im_auftrag_an_erster_stelle():
    """Was zuerst gefordert wird, bekommt die meiste Sorgfalt."""
    import inspect

    from insta_agent.brain import content

    quelle = inspect.getsource(content.create_post_draft)
    assert quelle.index("## image_generation_prompt") < quelle.index("## hook_text_on_screen")


def test_der_bildprompt_verlangt_platz_fuer_die_schrift():
    """Sonst steht der Hook auf einem unruhigen Bild und ist unlesbar."""
    import inspect

    from insta_agent.brain import content

    quelle = inspect.getsource(content.create_post_draft)
    assert "no text, no logos" in quelle
    assert "ruhige Fläche für die Schrift" in quelle


def test_ein_bild_darf_sich_nie_als_beleg_ausgeben():
    """Die eine Grenze, die bleibt.

    Fotorealismus ist erwuenscht - ein Titelbild im Magazin ist auch
    inszeniert. Was nicht geht, ist ein erzeugtes Bild, das vorgibt, der
    Beleg fuer die Zahl darunter zu sein. Genau das wuerde die
    Glaubwuerdigkeit zerstoeren, von der der Account lebt.
    """
    import inspect

    from insta_agent.brain import identity

    quelle = inspect.getsource(identity.invent_identity)
    assert "nie vorgeben, ein Beleg zu sein" in quelle
    assert "Inszeniert ja, dokumentarisch" in quelle


def test_die_bildsprache_soll_fotografisch_sein():
    """Vorher stand dort "keine dokumentarischen Aufnahmen" - das trieb ihn
    zu Farbflaechen mit Text darauf."""
    import inspect

    from insta_agent.brain import identity

    quelle = inspect.getsource(identity.invent_identity)
    assert "fotografisch sein" in quelle
    assert "Menschen dürfen darauf sein" in quelle
    # Die alte Einschraenkung darf nicht zurueckkommen.
    assert "keine realen Personen" not in quelle
