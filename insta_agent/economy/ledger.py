"""Die Kasse des Agenten.

Der Agent bezahlt seine eigene Rechenzeit aus einem Startkapital. Jeder
Modellaufruf wird als Ausgabe gebucht, jede Einnahme aus seinen Geschäften
als Eingang. Fällt der Kontostand, drosselt er sich selbst; ist er leer,
stoppt er und meldet sich beim Betreiber. Nachkaufen darf er nicht - das
bleibt eine bewusste menschliche Entscheidung.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..config import EconomyConfig
from ..store import Store

TREASURY_SEED_KEY = "treasury_seeded_usd"


class Mode(str, Enum):
    NORMAL = "normal"
    FRUGAL = "frugal"  # Sparbetrieb: billiges Modell, keine Webrecherche
    HALTED = "halted"  # Kasse leer


@dataclass(slots=True)
class TreasuryState:
    seed_usd: float
    """Was der Betreiber eingelegt hat. Kein Verdienst des Agenten."""

    spent_usd: float
    earned_usd: float
    """Nur selbst erwirtschaftete Einnahmen, ohne das Startkapital."""

    balance_usd: float
    mode: Mode
    cycle_spent_usd: float = 0.0

    @property
    def self_sustaining(self) -> bool:
        """Trägt sich der Agent selbst?

        Erst wahr, wenn die eigenen Einnahmen die eigenen Kosten decken.
        Das Startkapital zählt dabei ausdrücklich nicht mit - sonst würde
        sich der Agent für erfolgreich halten, solange fremdes Geld reicht.
        """
        return self.spent_usd > 0 and self.earned_usd >= self.spent_usd

    @property
    def cost_coverage(self) -> float:
        """Anteil der eigenen Kosten, den der Agent selbst deckt (0 bis 1+)."""
        return self.earned_usd / self.spent_usd if self.spent_usd > 0 else 0.0

    @property
    def runway_cycles(self) -> float:
        """Grobe Restlaufzeit, gemessen an bisherigen Durchschnittskosten."""
        return self.balance_usd / 0.25 if self.balance_usd > 0 else 0.0


class BudgetExhausted(RuntimeError):
    """Wird geworfen, wenn der Agent kein Geld mehr hat."""


class CycleBudgetExceeded(RuntimeError):
    """Wird geworfen, wenn ein einzelner Zyklus aus dem Ruder läuft."""


class Treasury:
    def __init__(self, store: Store, config: EconomyConfig) -> None:
        self.store = store
        self.config = config
        self._cycle_spent = 0.0
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        """Startkapital genau einmal einbuchen."""
        seeded = self.store.get_json(TREASURY_SEED_KEY)
        if seeded is None:
            self.store.add_ledger_entry(
                "revenue",
                "seed",
                self.config.treasury_start_usd,
                note="Startkapital des Betreibers",
            )
            self.store.set_json(TREASURY_SEED_KEY, self.config.treasury_start_usd)

    # -- Buchungen ---------------------------------------------------------

    def charge(self, amount_usd: float, category: str, note: str = "", meta: object = None) -> None:
        """Bucht eine Ausgabe, typischerweise einen Modellaufruf."""
        if amount_usd <= 0:
            return
        self.store.add_ledger_entry("cost", category, -abs(amount_usd), note, meta)
        self._cycle_spent += abs(amount_usd)

    def earn(self, amount_usd: float, category: str, note: str = "", meta: object = None) -> None:
        """Bucht eine Einnahme aus einem Geschäft des Agenten."""
        self.store.add_ledger_entry("revenue", category, abs(amount_usd), note, meta)

    # -- Zustand -----------------------------------------------------------

    def state(self) -> TreasuryState:
        spent = abs(self.store.ledger_sum("cost"))
        seed = self.store.ledger_sum("revenue") - self.store.ledger_sum_excluding("revenue", "seed")
        earned = self.store.ledger_sum_excluding("revenue", "seed")
        balance = seed + earned - spent

        if balance < self.config.halt_balance_usd:
            mode = Mode.HALTED
        elif balance < self.config.low_balance_usd:
            mode = Mode.FRUGAL
        else:
            mode = Mode.NORMAL

        return TreasuryState(
            seed_usd=seed,
            spent_usd=spent,
            earned_usd=earned,
            balance_usd=balance,
            mode=mode,
            cycle_spent_usd=self._cycle_spent,
        )

    def begin_cycle(self) -> None:
        self._cycle_spent = 0.0

    def check(self) -> TreasuryState:
        """Vor jedem teuren Schritt aufrufen. Wirft, wenn Schluss ist."""
        state = self.state()
        if state.mode is Mode.HALTED:
            raise BudgetExhausted(
                f"Kasse leer: {state.balance_usd:.4f} USD übrig "
                f"(Grenze {self.config.halt_balance_usd:.2f} USD). "
                "Der Agent stoppt und wartet auf eine Entscheidung des Betreibers."
            )
        if self._cycle_spent >= self.config.max_cost_per_cycle_usd:
            raise CycleBudgetExceeded(
                f"Zyklusbudget aufgebraucht: {self._cycle_spent:.4f} USD von "
                f"{self.config.max_cost_per_cycle_usd:.2f} USD."
            )
        return state
