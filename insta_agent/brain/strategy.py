"""Kursbestimmung: aus Zahlen und Recherche wird ein Plan für die Woche."""

from __future__ import annotations

from ..llm import Brain
from ..models import MarketAnalysis, Reflection, StrategyUpdate
from .prompts import PERSONA, identity_block, strategy_block, treasury_block, with_context


def update_strategy(
    brain: Brain,
    *,
    identity,
    previous: StrategyUpdate | None,
    analysis: MarketAnalysis | None,
    reflection: Reflection | None,
    performance: str,
    treasury_state,
) -> StrategyUpdate:
    return brain.structured(
        schema=StrategyUpdate,
        system=PERSONA,
        label="Strategie festlegen",
        prompt=with_context(
            identity_block(identity),
            strategy_block(previous),
            treasury_block(treasury_state),
            f"# Deine Zahlen\n{performance}",
            f"# Was die Recherche sagt\n{analysis.summary}\nChancen: {', '.join(analysis.content_opportunities)}"
            if analysis
            else "",
            f"""\
# Was du beim letzten Mal gelernt hast
Funktioniert: {", ".join(reflection.what_worked) or "noch nichts belastbar"}
Funktioniert nicht: {", ".join(reflection.what_failed) or "noch nichts belastbar"}
Deine nächsten Schritte: {", ".join(reflection.next_actions)}"""
            if reflection
            else "",
            """\
# Auftrag
Lege den Kurs für die nächsten sieben Tage fest.

Ein Ziel, nicht fünf. Es muss messbar sein und in sieben Tagen erreichbar.
Wenn du noch kaum Daten hast, ist das richtige Ziel, welche zu bekommen -
dann baust du bewusst Varianten, die sich unterscheiden lassen.

Nenne bei jeder Änderung, was du vorher gemacht hast und warum du es jetzt
anders machst. Änderungen ohne Anlass sind Unruhe, keine Strategie: wenn
etwas läuft, lass es laufen und schreib das hin.

Beachte deinen Kontostand. Bei knapper Kasse planst du weniger Posts und
mehr Wirkung pro Post, nicht umgekehrt.""",
        ),
    )
