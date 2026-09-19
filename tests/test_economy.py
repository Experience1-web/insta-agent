"""Die Budgetbremse ist die wichtigste Sicherung des Agenten."""

import pytest

from insta_agent.economy.ledger import BudgetExhausted, CycleBudgetExceeded, Mode
from insta_agent.economy.pricing import cost_of_usage, price_for


class FakeUsage:
    def __init__(self, input_tokens=0, output_tokens=0, cache_read=0, cache_write=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read
        self.cache_creation_input_tokens = cache_write


def test_startkapital_wird_genau_einmal_gebucht(store, economy):
    from insta_agent.economy.ledger import Treasury

    Treasury(store, economy)
    Treasury(store, economy)  # zweiter Start darf nicht nochmal gutschreiben
    assert store.ledger_sum("revenue") == pytest.approx(10.0)


def test_kosten_werden_als_negativ_gebucht(treasury, store):
    treasury.charge(1.25, "llm", "Test")
    assert store.ledger_sum("cost") == pytest.approx(-1.25)
    assert treasury.state().balance_usd == pytest.approx(8.75)


def test_modus_wechselt_mit_dem_kontostand(treasury):
    assert treasury.state().mode is Mode.NORMAL
    treasury.charge(7.5, "llm")  # Rest 2.50, unter low_balance 3.00
    assert treasury.state().mode is Mode.FRUGAL
    treasury.charge(2.2, "llm")  # Rest 0.30, unter halt_balance 0.50
    assert treasury.state().mode is Mode.HALTED


def test_check_stoppt_bei_leerer_kasse(treasury):
    treasury.charge(9.8, "llm")
    with pytest.raises(BudgetExhausted):
        treasury.check()


def test_zyklusbudget_begrenzt_einen_einzelnen_lauf(treasury):
    treasury.begin_cycle()
    treasury.charge(1.0, "llm")  # genau die Obergrenze pro Zyklus
    with pytest.raises(CycleBudgetExceeded):
        treasury.check()


def test_zyklusbudget_wird_pro_zyklus_zurueckgesetzt(treasury):
    treasury.begin_cycle()
    treasury.charge(1.0, "llm")
    treasury.begin_cycle()
    assert treasury.check().mode is Mode.NORMAL


def test_einnahmen_machen_den_agenten_selbsttragend(treasury):
    treasury.charge(2.0, "llm")
    assert not treasury.state().self_sustaining
    treasury.earn(5.0, "digital_product", "Erster Verkauf")
    assert treasury.state().self_sustaining
    assert treasury.state().balance_usd == pytest.approx(13.0)


def test_preisberechnung_trennt_frische_und_gecachte_token():
    # 1 Mio Eingabe + 1 Mio Ausgabe auf Opus 5 = 5 + 25 USD
    assert cost_of_usage("claude-opus-5", FakeUsage(1_000_000, 1_000_000)) == pytest.approx(30.0)
    # Cache-Treffer kosten ein Zehntel der frischen Eingabe
    assert cost_of_usage("claude-opus-5", FakeUsage(cache_read=1_000_000)) == pytest.approx(0.5)


def test_unbekanntes_modell_wird_teuer_geschaetzt():
    """Lieber überschätzen - eine Unterschätzung hebelt die Bremse aus."""
    unknown = price_for("claude-gibt-es-nicht")
    assert unknown.input_per_mtok >= price_for("claude-opus-5").input_per_mtok


def test_startkapital_zaehlt_nicht_als_verdienst(treasury):
    """Fremdes Geld darf den Agenten nicht für selbsttragend halten lassen."""
    treasury.charge(2.0, "llm")
    state = treasury.state()
    assert state.seed_usd == pytest.approx(10.0)
    assert state.earned_usd == pytest.approx(0.0)
    assert not state.self_sustaining


def test_kostendeckung_waechst_mit_den_einnahmen(treasury):
    treasury.charge(4.0, "llm")
    assert treasury.state().cost_coverage == pytest.approx(0.0)
    treasury.earn(2.0, "affiliate")
    assert treasury.state().cost_coverage == pytest.approx(0.5)


def test_eine_gemeldete_einnahme_hebt_den_sparbetrieb_auf(treasury):
    """Der Weg, auf dem der Agent von seinem Verdienst erfährt."""
    from insta_agent.economy.ledger import Mode

    treasury.charge(7.5, "llm")
    assert treasury.state().mode is Mode.FRUGAL

    # 6 USD decken 7.50 USD Kosten noch nicht - Sparbetrieb ist aufgehoben,
    # selbsttragend ist der Agent damit aber noch nicht.
    treasury.earn(6.0, "digital_product", "Erste Verkäufe")
    state = treasury.state()
    assert state.mode is Mode.NORMAL
    assert not state.self_sustaining
    assert state.cost_coverage == pytest.approx(0.8)

    # Erst ab voller Deckung.
    treasury.earn(1.5, "digital_product", "Weitere Verkäufe")
    assert treasury.state().self_sustaining
