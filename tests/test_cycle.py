"""Der vollständige Zyklus - mit einem gefälschten Modell statt echter API.

Damit ist prüfbar, dass Gedächtnis, Kasse, Bilderzeugung und Entwurfsablage
zusammenspielen, ohne dass ein einziger Token bezahlt wird.
"""

import pytest

from insta_agent.config import EconomyConfig, LLMConfig, PostingConfig, Settings
from insta_agent.llm import CallResult
from insta_agent.models import (
    BusinessIdea,
    Competitor,
    Gestaltungsurteil,
    Identity,
    MarketAnalysis,
    MonetizationPlan,
    PostDraft,
    Pruefbericht,
    Reflection,
    StrategyUpdate,
    VisualSpec,
)
from insta_agent.runner import Agent

# Je Aufruf ein fester Preis, damit die Kosten im Test nachrechenbar sind.
KOSTEN_PRO_AUFRUF = 0.02


class FakeBrain:
    """Liefert für jedes Schema eine plausible Antwort und bucht Kosten."""

    def __init__(self, config, treasury, api_key=None):
        self.treasury = treasury
        self.aufrufe: list[str] = []
        self.suchbudget = config.max_web_searches
        self.letzte_quellen: list[str] = []
        # Womit gesucht wurde, damit Tests das nachsehen koennen.
        self.gesucht: list[str] = []

    def _buchen(self, label: str) -> None:
        self.treasury.check()
        self.treasury.charge(KOSTEN_PRO_AUFRUF, "llm", label)
        self.aufrufe.append(label)

    def text(self, *, system, prompt, label, task="reasoning", web_search=False, max_rounds=6):
        self._buchen(label)
        return CallResult(
            text="Kurzform-Videos wachsen, Zitatkacheln sind übersättigt.",
            cost_usd=KOSTEN_PRO_AUFRUF,
            model="fake",
            sources=["https://beispiel.de/studie"] if web_search else [],
        )

    def structured(
        self, *, schema, system, prompt, label, task="reasoning", web_search=False, max_rounds=6
    ):
        self._buchen(label)
        if web_search:
            self.gesucht.append(label)
            self.letzte_quellen = ["https://beispiel.de/quelle"]
        return _ANTWORTEN[schema]()


def _analyse() -> MarketAnalysis:
    return MarketAnalysis(
        summary="Die Nische wächst, ist aber flach besetzt.",
        trends=["kurze Textvideos", "ehrliche Rückschlagsgeschichten"],
        competitors=[
            Competitor(
                handle_or_name="@vorbild",
                what_they_do_well="klare Bildsprache",
                gap_we_can_exploit="keine konkreten Schritte",
            )
        ],
        content_opportunities=["Schritt-für-Schritt-Anleitungen"],
        risks=["Zitatkacheln sind übersättigt"],
        confidence="medium",
        sources=[],
    )


def _identitaet() -> Identity:
    return Identity(
        agent_name="Mara Vogt",
        agent_why="Ein Name, unter dem man mich ansprechen kann.",
        handle="kleineschritte",
        display_name="Kleine Schritte",
        motto="Wer klein anfängt, hört nicht auf.",
        niche="Gewohnheiten für Berufstätige",
        target_audience="Berufstätige zwischen 25 und 40",
        tone_of_voice="direkt, ohne Floskeln",
        visual_identity="dunkle Flächen, harte Typografie, ein Akzentton",
        content_pillars=["Gewohnheiten", "Fokus", "Rückschläge"],
        bio="Kleine Schritte, jeden Tag.",
        why_this_works="Die Nische ist groß und schlecht besetzt.",
    )


def _strategie() -> StrategyUpdate:
    return StrategyUpdate(
        current_goal="In sieben Tagen 50 Speicherungen erreichen.",
        reasoning="Speicherungen sagen mehr über Wert aus als Likes.",
        changes=["Anleitungen statt Zitate"],
        posting_cadence="täglich um 8 Uhr",
        kpis_to_watch=["Speicherungen", "Reichweite"],
        experiments=["Zwei Einstiegsformen gegeneinander testen"],
    )


def _entwurf() -> PostDraft:
    return PostDraft(
        pillar="Gewohnheiten",
        # Das echte Modell liefert diese Felder - das Doppel muss es auch,
        # sonst laufen Bilderzeugung und Freigabe im Test ins Leere.
        hook_text_on_screen="Du brauchst keinen neuen Plan.",
        image_generation_prompt=(
            "A single worn notebook on a dark wooden table, one cold window "
            "light from the left, deep shadows, 35mm film grain, no text, "
            "no logos, empty space in the upper third, vertical 9:16"
        ),
        body_text="Du brauchst einen kleineren.",
        first_comment_prompt="Welcher Plan von dir ist schon dreimal gescheitert?",
        hook="Du brauchst keinen neuen Plan.",
        caption="Du brauchst keinen neuen Plan.\n\nDu brauchst einen kleineren.",
        hashtags=["gewohnheiten", "fokus"],
        call_to_action="Speichere das für Montag.",
        visual=VisualSpec(
            headline="Du brauchst keinen neuen Plan.",
            subline="Du brauchst einen kleineren",
            body_lines=["Fünf Minuten statt einer Stunde"],
            background_hex="#111318",
            text_hex="#F5F5F0",
            accent_hex="#E4572E",
        ),
        best_time_hint="Montag 8 Uhr",
        expected_outcome="mehr Speicherungen als sonst",
    )


def _gestaltungsurteil() -> Gestaltungsurteil:
    """Die Bildsprache ist zufrieden und laesst den Prompt, wie er ist."""
    return Gestaltungsurteil(
        niveau=4,
        urteil="Der Ausschnitt sitzt, das Licht hat eine Richtung.",
        staerken=["Harte Kante oben links"],
        bildprompt="",
    )


def _pruefbericht() -> Pruefbericht:
    """Die Endprüfung findet nichts - das ist der Normalfall im Test.

    Wer den angehaltenen Beitrag prüfen will, baut sich einen eigenen
    Bericht; hier soll der Zyklus durchlaufen.
    """
    return Pruefbericht(
        urteil="freigabe",
        zusammenfassung="Keine Zahl, keine Quellenangabe, nichts zu beanstanden.",
        befunde=[],
    )


def _reflexion() -> Reflection:
    return Reflection(
        what_worked=["Anleitungen"],
        what_failed=["reine Zitate"],
        hypotheses=["Konkretes wird eher gespeichert"],
        next_actions=["mehr Anleitungen"],
        strategy_should_change=False,
    )


def _geschaeftsplan() -> MonetizationPlan:
    return MonetizationPlan(
        reasoning="Ein kleines digitales Produkt geht am schnellsten.",
        ideas=[
            BusinessIdea(
                name="Gewohnheits-Vorlage",
                pitch="Eine Seite, die den Wochenstart plant.",
                revenue_model="digital_product",
                price_point_usd=7.0,
                required_followers=500,
                effort="low",
                first_step="Vorlage schreiben",
                fits_identity_because="passt zu den kleinen Schritten",
                monthly_revenue_estimate_usd=0.0,
            )
        ],
        recommended_now="Gewohnheits-Vorlage",
        what_the_operator_must_do=["Zahlungsanbieter einrichten"],
    )


_ANTWORTEN = {
    MarketAnalysis: _analyse,
    Identity: _identitaet,
    StrategyUpdate: _strategie,
    PostDraft: _entwurf,
    Reflection: _reflexion,
    MonetizationPlan: _geschaeftsplan,
    Pruefbericht: _pruefbericht,
    Gestaltungsurteil: _gestaltungsurteil,
}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        llm=LLMConfig(),
        economy=EconomyConfig(
            treasury_start_usd=5.0,
            low_balance_usd=1.0,
            halt_balance_usd=0.25,
            max_cost_per_cycle_usd=1.0,
        ),
        posting=PostingConfig(posts_per_day=1, live=False),
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )


@pytest.fixture
def agent(settings, monkeypatch):
    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    yield a
    a.close()


def test_erster_zyklus_erfindet_das_profil_und_legt_einen_entwurf_ab(agent):
    report = agent.run_cycle()

    assert report.halted_reason is None
    assert agent.identity.motto == "Wer klein anfängt, hört nicht auf."
    assert agent.strategy.current_goal.startswith("In sieben Tagen")

    # Ein Entwurf mit Bild, aber nichts veröffentlicht.
    assert len(report.drafts_written) == 1
    assert report.published_media_ids == []
    entwuerfe = agent.store.pending_drafts()
    assert len(entwuerfe) == 1
    assert entwuerfe[0]["image_path"].endswith(".png")


def test_das_bild_wird_wirklich_erzeugt(agent):
    agent.run_cycle()
    from pathlib import Path

    bild = Path(agent.store.pending_drafts()[0]["image_path"])
    assert bild.exists() and bild.stat().st_size > 1000


def test_der_agent_bezahlt_seinen_eigenen_zyklus(agent):
    vorher = agent.treasury.state().balance_usd
    report = agent.run_cycle()
    nachher = agent.treasury.state().balance_usd

    assert report.cost_usd > 0
    assert nachher == pytest.approx(vorher - report.cost_usd)


def test_zweiter_zyklus_erfindet_sich_nicht_neu(agent):
    agent.run_cycle()
    erstes_motto = agent.identity.motto
    agent.run_cycle()

    assert agent.identity.motto == erstes_motto
    # Zwei Zyklen, zwei Entwürfe.
    assert len(agent.store.pending_drafts()) == 2


def test_leere_kasse_haelt_den_agenten_an(agent):
    agent.treasury.charge(4.9, "llm", "Vorlauf")  # Rest 0.10, unter der Grenze
    report = agent.run_cycle()

    assert report.halted_reason is not None
    assert "Kasse leer" in report.halted_reason
    # Nichts wurde produziert, während die Kasse leer war.
    assert agent.store.pending_drafts() == []


def test_zyklusbudget_bremst_einen_ausreisser(agent, settings):
    settings.economy.max_cost_per_cycle_usd = 0.05  # reicht nur für zwei Aufrufe
    report = agent.run_cycle()

    assert report.halted_reason is not None
    assert "Zyklusbudget" in report.halted_reason


def test_das_protokoll_haelt_den_zyklus_fest(agent):
    agent.run_cycle()
    arten = {row["kind"] for row in agent.store.recent_journal(50)}
    assert {"identity", "metrics", "cycle"} <= arten


def test_eine_teure_recherche_geht_nicht_verloren(monkeypatch):
    """Scheitert das billige Ordnen, bleibt die bezahlte Recherche erhalten."""
    from insta_agent.brain.research import run_market_research
    from insta_agent.llm import CallResult

    class HalbKaputtesBrain:
        """Die Websuche gelingt, das Strukturieren nicht."""

        suchbudget = 4

        def text(self, **kwargs):
            return CallResult(
                text="Kurzvideos wachsen stark, Zitatkacheln sind übersättigt.",
                cost_usd=0.49,
                model="claude-opus-5",
                sources=["https://beispiel.de/studie"],
            )

        def structured(self, **kwargs):
            raise RuntimeError("This model does not support the effort parameter.")

    analyse = run_market_research(HalbKaputtesBrain(), identity=None)

    assert "Kurzvideos" in analyse.summary
    assert analyse.sources == ["https://beispiel.de/studie"]
    # Als unsicher gekennzeichnet, damit der Agent nicht zu viel darauf gibt.
    assert analyse.confidence == "low"


def test_eine_bezahlte_recherche_wird_beim_zweiten_versuch_wiederverwendet(agent, monkeypatch):
    """Bricht der Geburtszyklus ab, darf der nächste nicht neu einkaufen."""
    from insta_agent.runner import KEY_ANALYSIS

    aufrufe = {"n": 0}
    echte_recherche = None

    def zaehlende_recherche(brain, **kwargs):
        aufrufe["n"] += 1
        return _analyse()

    monkeypatch.setattr("insta_agent.runner.run_market_research", zaehlende_recherche)

    # Erster Versuch: Recherche läuft, danach bricht es ab.
    def platzt(*a, **k):
        raise RuntimeError("Budget alle")

    monkeypatch.setattr("insta_agent.runner.invent_identity", platzt)
    with pytest.raises(RuntimeError):
        agent.bootstrap()

    assert aufrufe["n"] == 1
    assert agent.store.get_json(KEY_ANALYSIS) is not None

    # Zweiter Versuch: kein weiterer Rechercheaufruf.
    monkeypatch.setattr("insta_agent.runner.invent_identity", lambda *a, **k: _identitaet())
    agent.bootstrap()

    assert aufrufe["n"] == 1, "die Recherche wurde ein zweites Mal bezahlt"
    assert agent.identity is not None
