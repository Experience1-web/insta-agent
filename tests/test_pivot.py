"""Wann darf der Agent seinen Kurs wechseln?

Jede Bedingung hier kostet Geld, wenn man sie weglässt: Ein Account, der
ständig die Nische tauscht, baut nie Publikum auf - und jeder einzelne
Wechsel sieht dabei für sich genommen vernünftig aus.
"""

import pytest

from insta_agent.models import Opportunity, OpportunityAssessment
from insta_agent.runner import PIVOT_MINDESTABSTAND, Agent
from test_cycle import FakeBrain  # noqa: F401 - über conftest-Pfad erreichbar


def _chance(*, wert: float, wahrscheinlichkeit: float, name: str = "Alternative") -> Opportunity:
    return Opportunity(
        name=name,
        description="etwas anderes",
        revenue_model="digital_product",
        value_if_it_works_usd=wert,
        probability=wahrscheinlichkeit,
        days_to_first_dollar=30,
        effort="medium",
        needs_new_audience=True,
        why="geschätzt",
    )


def _bewertung(
    *,
    jetzt: float,
    chance: Opportunity | None,
    empfehlung: str = "wechseln",
    sicherheit: str = "high",
) -> OpportunityAssessment:
    return OpportunityAssessment(
        current_path_value_usd=jetzt,
        current_path_reasoning="hochgerechnet",
        opportunities=[chance] if chance else [],
        switching_cost="Reichweite weg",
        recommendation=empfehlung,
        reasoning="weil",
        confidence=sicherheit,
    )


@pytest.fixture
def agent(tmp_path, monkeypatch):
    from insta_agent.config import EconomyConfig, PostingConfig, Settings

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(
        Settings(
            economy=EconomyConfig(treasury_start_usd=20.0),
            posting=PostingConfig(),
            db_path=tmp_path / "a.db",
            media_dir=tmp_path / "m",
            draft_dir=tmp_path / "d",
        )
    )
    yield a
    a.close()


def test_erwartungswert_schlaegt_die_grosse_zahl():
    """5 Prozent Chance auf 10.000 USD sind 500 USD wert, nicht 10.000."""
    assert _chance(wert=10_000, wahrscheinlichkeit=0.05).expected_value_usd == 500


def test_knapp_besser_reicht_nicht(agent):
    """Ein Wechsel muss sich lohnen, nicht bloß interessant aussehen."""
    bewertung = _bewertung(jetzt=100, chance=_chance(wert=300, wahrscheinlichkeit=0.5))  # EV 150
    grund = agent._wechsel_abgelehnt(bewertung, bewertung.opportunities[0], cycle=20, letzter_wechsel=0)

    assert grund is not None
    assert "150" in grund and "200" in grund


def test_deutlich_besser_wird_zugelassen(agent):
    bewertung = _bewertung(jetzt=100, chance=_chance(wert=1000, wahrscheinlichkeit=0.5))  # EV 500
    assert agent._wechsel_abgelehnt(bewertung, bewertung.opportunities[0], cycle=20, letzter_wechsel=0) is None


def test_zu_kurz_nach_dem_letzten_wechsel(agent):
    bewertung = _bewertung(jetzt=10, chance=_chance(wert=10_000, wahrscheinlichkeit=1.0))
    grund = agent._wechsel_abgelehnt(
        bewertung, bewertung.opportunities[0], cycle=15, letzter_wechsel=12
    )

    assert grund is not None and "Mindestabstand" in grund


def test_nach_ablauf_der_sperre_wieder_erlaubt(agent):
    bewertung = _bewertung(jetzt=10, chance=_chance(wert=10_000, wahrscheinlichkeit=1.0))
    spaeter = 12 + PIVOT_MINDESTABSTAND
    assert agent._wechsel_abgelehnt(bewertung, bewertung.opportunities[0], cycle=spaeter, letzter_wechsel=12) is None


def test_unsichere_einschaetzung_wechselt_nicht(agent):
    bewertung = _bewertung(
        jetzt=10, chance=_chance(wert=10_000, wahrscheinlichkeit=1.0), sicherheit="low"
    )
    grund = agent._wechsel_abgelehnt(bewertung, bewertung.opportunities[0], cycle=20, letzter_wechsel=0)
    assert grund is not None and "unsicher" in grund


def test_ohne_benannte_alternative_kein_wechsel(agent):
    bewertung = _bewertung(jetzt=10, chance=None)
    grund = agent._wechsel_abgelehnt(bewertung, None, cycle=20, letzter_wechsel=0)
    assert grund is not None and "keine Alternative" in grund


def test_bei_null_einnahmen_genuegt_ein_kleiner_betrag(agent):
    """Wer nichts verdient, soll nicht wegen der Faktorregel festsitzen."""
    bewertung = _bewertung(jetzt=0.0, chance=_chance(wert=20, wahrscheinlichkeit=0.5))  # EV 10
    assert agent._wechsel_abgelehnt(bewertung, bewertung.opportunities[0], cycle=20, letzter_wechsel=0) is None


def test_weitermachen_loest_nie_einen_wechsel_aus(agent):
    """Sagt der Agent selbst "weitermachen", darf nichts gewechselt werden.

    Dass hier ein Grund zurückkommt, ist der Punkt: None hieße "kein
    Einwand" und würde die Neuausrichtung auslösen - selbst gegen den
    ausdrücklichen Rat des Agenten.
    """
    for empfehlung in ("weitermachen", "ergaenzen"):
        bewertung = _bewertung(
            jetzt=10,
            chance=_chance(wert=10_000, wahrscheinlichkeit=1.0),
            empfehlung=empfehlung,
        )
        grund = agent._wechsel_abgelehnt(
            bewertung, bewertung.opportunities[0], cycle=20, letzter_wechsel=0
        )
        assert grund, f"{empfehlung} hätte einen Wechsel ausgelöst"


# --- Der Wechsel selbst ---------------------------------------------------


def test_beim_wechsel_bleibt_die_person_und_der_verlauf_erhalten(agent, monkeypatch):
    """Die Marke wechselt, der Agent bleibt derselbe - und weiß, warum."""
    from datetime import datetime, timezone

    from insta_agent.models import CycleReport
    from insta_agent.runner import KEY_IDENTITY_HISTORY, KEY_LAST_PIVOT, KEY_STRATEGY

    alt = agent.bootstrap()
    agent.store.set_json(KEY_STRATEGY, {"irgendwas": "altes"})

    bewertung = _bewertung(jetzt=10, chance=_chance(wert=5000, wahrscheinlichkeit=0.9))
    monkeypatch.setattr("insta_agent.runner.assess_opportunities", lambda *a, **k: bewertung)

    bericht = CycleReport(started_at=datetime.now(timezone.utc))
    neu = agent._pruefe_kurs(5, alt, "keine Zahlen", bericht)

    # Die Person bleibt, damit der Account nicht zum Karussell wird.
    assert neu.agent_name == alt.agent_name

    # Der Grund des Wechsels ist nachlesbar.
    verlauf = agent.store.get_json(KEY_IDENTITY_HISTORY)
    assert len(verlauf) == 1
    assert verlauf[0]["identitaet"]["handle"] == alt.handle
    assert verlauf[0]["neue_richtung"] == "Alternative"

    # Der alte Kurs gilt nicht mehr, sonst plant er gegen sich selbst.
    assert agent.store.get_json(KEY_STRATEGY) is None
    assert agent.store.get_json(KEY_LAST_PIVOT) == 5

    assert any("Neuausrichtung" in s for s in bericht.steps)


def test_nach_einem_wechsel_greift_die_sperre(agent, monkeypatch):
    from datetime import datetime, timezone

    from insta_agent.models import CycleReport

    alt = agent.bootstrap()
    bewertung = _bewertung(jetzt=10, chance=_chance(wert=5000, wahrscheinlichkeit=0.9))
    monkeypatch.setattr("insta_agent.runner.assess_opportunities", lambda *a, **k: bewertung)

    agent._pruefe_kurs(5, alt, "x", CycleReport(started_at=datetime.now(timezone.utc)))
    aktuell = agent.identity

    # Gleich der nächste Prüfzyklus - jetzt muss die Sperre greifen.
    bericht = CycleReport(started_at=datetime.now(timezone.utc))
    danach = agent._pruefe_kurs(10, aktuell, "x", bericht)

    assert danach.handle == aktuell.handle
    assert any("Mindestabstand" in s for s in bericht.steps)
