import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from insta_agent.config import EconomyConfig  # noqa: E402
from insta_agent.economy.ledger import Treasury  # noqa: E402
from insta_agent.models import PostDraft, VisualSpec  # noqa: E402
from insta_agent.store import Store  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def economy():
    return EconomyConfig(
        treasury_start_usd=10.0,
        low_balance_usd=3.0,
        halt_balance_usd=0.5,
        max_cost_per_cycle_usd=1.0,
    )


@pytest.fixture
def treasury(store, economy):
    return Treasury(store, economy)


@pytest.fixture
def draft():
    return PostDraft(
        pillar="Gewohnheiten",
        hook="Niemand folgt dir für Perfektion.",
        caption="Niemand folgt dir für Perfektion.\n\nSondern für Wiedererkennbarkeit.",
        hashtags=["wachstum", "gewohnheiten", "disziplin"],
        call_to_action="Speichere das für Montag.",
        visual=VisualSpec(
            headline="Niemand folgt dir für Perfektion.",
            subline="Wiedererkennbarkeit schlägt Makellosigkeit",
            body_lines=["Gleiche Farben", "Gleiche Stimme"],
            background_hex="#111318",
            text_hex="#F5F5F0",
            accent_hex="#E4572E",
            footer="@beispiel",
        ),
        best_time_hint="Montag 8 Uhr, Wochenstart",
        expected_outcome="Speicherungen über dem Schnitt",
    )
