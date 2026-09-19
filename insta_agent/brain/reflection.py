"""Der Agent schaut sich seine eigenen Zahlen an und zieht Konsequenzen."""

from __future__ import annotations

from ..llm import Brain
from ..models import Reflection
from .prompts import PERSONA, identity_block, strategy_block, with_context


def reflect(brain: Brain, *, identity, strategy, performance: str, post_history: str) -> Reflection:
    return brain.structured(
        schema=Reflection,
        system=PERSONA,
        label="Reflexion",
        prompt=with_context(
            identity_block(identity),
            strategy_block(strategy),
            f"# Deine Kennzahlen\n{performance}",
            f"# Deine letzten Posts\n{post_history}",
            """\
# Auftrag
Sieh dir an, was du getan hast und was dabei herauskam.

Halte auseinander, was du wirklich weißt und was du nur vermutest. Bei
wenigen Posts sind Unterschiede meist Zufall - sag das offen, statt aus
drei Datenpunkten ein Gesetz zu machen. Deine Hypothesen gehören in das
Feld für Hypothesen, nicht zu den Erkenntnissen.

Wenn deine Zahlen flach sind, such den Grund nicht beim Algorithmus. Such
ihn beim Inhalt: Ist der Einstieg zu schwach, das Versprechen zu vage, das
Bild zu beliebig?

strategy_should_change setzt du nur auf true, wenn du einen belegbaren
Grund hast. Ständiger Kurswechsel ist das häufigste Scheitern.""",
        ),
    )
