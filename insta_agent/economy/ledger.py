"""Die Kasse des Agenten.

Der Agent bezahlt seine eigene Rechenzeit aus einem Startkapital. Jeder
Modellaufruf wird als Ausgabe gebucht, jede Einnahme aus seinen Geschäften
als Eingang. Fällt der Kontostand, drosselt er sich selbst; ist er leer,
stoppt er und meldet sich beim Betreiber. Nachkaufen darf er nicht - das
bleibt eine bewusste menschliche Entscheidung.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ..config import EconomyConfig
from ..store import Store

TREASURY_SEED_KEY = "treasury_seeded_usd"
TREASURY_ANKER_KEY = "treasury_anker"

# Geld, das vom Betreiber kommt und nicht vom Agenten verdient wurde:
# das Startkapital und spätere Korrekturen am Kontostand. Beides darf
# nicht als Verdienst durchgehen, sonst hält der Agent sich für
# selbsttragend, solange fremdes Geld reicht.
BETREIBERGELD = ("seed", "abgleich")


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

    def setze_anker(self, guthaben: float, bereits_heute: float | None = None) -> float:
        """Merkt sich einen echten Kontostand als Ausgangspunkt.

        `bereits_heute` ist, was an diesem Tag vor dem Eintragen schon
        angefallen ist. Die Abrechnung löst nur ganze Tage auf, also muss
        dieser Teil später wieder abgezogen werden - sonst würde er ein
        zweites Mal vom Guthaben abgehen.

        Ohne diesen Wert bleibt es beim Eintragen von Hand: Es fehlt der
        Bezugspunkt, um später allein weiterzurechnen.
        """
        self.store.set_json(
            TREASURY_ANKER_KEY,
            {
                "zeitpunkt": datetime.now(timezone.utc).isoformat(),
                "guthaben": float(guthaben),
                "bereits": None if bereits_heute is None else float(bereits_heute),
            },
        )
        return self.abgleichen(guthaben)

    def anker(self) -> dict | None:
        return self.store.get_json(TREASURY_ANKER_KEY)

    def rechnet_selbst(self) -> bool:
        """Ob der Agent seinen Stand ohne Zutun fortschreiben kann."""
        anker = self.anker()
        return bool(anker) and anker.get("bereits") is not None

    def aus_abrechnung(self, abrechnung: object) -> float | None:
        """Schreibt den Kontostand aus der echten Abrechnung fort.

        Gibt die gebuchte Differenz zurück, oder None, wenn es nichts
        fortzuschreiben gibt - dann bleibt es bei der Schätzung.
        """
        anker = self.anker()
        if not anker or anker.get("bereits") is None:
            return None

        seit = datetime.fromisoformat(anker["zeitpunkt"])
        # Was seit dem Ankertag abgerechnet wurde, ohne den Teil dieses
        # Tages, der schon vor dem Ankern angefallen war.
        verbraucht = abrechnung.kosten_seit(seit) - float(anker["bereits"])
        return self.abgleichen(float(anker["guthaben"]) - max(verbraucht, 0.0))

    def abgleichen(self, ist_guthaben: float) -> float:
        """Setzt den Kontostand auf den echten Wert und gibt die Differenz zurück.

        Die Kasse rechnet mit, was ein Modellaufruf kosten *sollte* - aus
        Tokenzahl und Preisliste. Das ist eine Schätzung: Preise ändern
        sich, und nicht jede Ausgabe läuft über den Agenten. Der Wert auf
        der Abrechnungsseite ist die Wahrheit, also muss er sich eintragen
        lassen.

        Gebucht wird die Differenz, nicht der Endstand. So bleibt in der
        Geschichte stehen, was wirklich passiert ist - und die Korrektur
        zählt ausdrücklich nicht als Verdienst.
        """
        differenz = round(ist_guthaben - self.state().balance_usd, 6)
        if differenz == 0:
            return 0.0
        self.store.add_ledger_entry(
            "revenue" if differenz > 0 else "cost",
            "abgleich",
            differenz,
            note=f"Abgleich mit dem echten Konto: {ist_guthaben:.2f} USD",
        )
        return differenz

    # -- Zustand -----------------------------------------------------------

    def state(self) -> TreasuryState:
        spent = abs(self.store.ledger_sum("cost"))
        seed = self.store.ledger_sum("revenue") - self.store.ledger_sum_excluding(
            "revenue", BETREIBERGELD
        )
        earned = self.store.ledger_sum_excluding("revenue", BETREIBERGELD)
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
