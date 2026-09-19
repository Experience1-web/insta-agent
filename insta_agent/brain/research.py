"""Marktrecherche: der Agent schaut sich selbst um, bevor er entscheidet."""

from __future__ import annotations

import logging

from ..llm import Brain
from ..models import MarketAnalysis
from .prompts import PERSONA, identity_block, with_context

log = logging.getLogger(__name__)


def run_market_research(brain: Brain, *, identity=None, focus: str | None = None) -> MarketAnalysis:
    """Zwei Schritte: erst frei recherchieren, dann das Ergebnis ordnen.

    Die Websuche läuft als Server-Tool und liefert Fließtext. Den bringt
    ein zweiter, billiger Aufruf in die feste Struktur - das ist robuster
    als beides in einem Zug zu verlangen.
    """
    topic = focus or (identity.niche if identity else "noch offen - du suchst dir eine Nische")

    research = brain.text(
        system=PERSONA,
        label="Marktrecherche",
        task="research",
        web_search=True,
        prompt=with_context(
            identity_block(identity),
            f"""\
# Auftrag
Recherchiere den aktuellen Stand für diesen Bereich auf Instagram: {topic}

Suche gezielt nach:
- Welche Formate und Themen dort gerade Reichweite bekommen
- Welche Accounts das Feld besetzen und was ihnen fehlt
- Welche Lücke ein neuer Account glaubwürdig besetzen kann
- Was gerade übersättigt ist und wovon du die Finger lassen solltest

Schreibe das Ergebnis als dichten Fließtext. Nenne Zahlen, wo du welche
findest, und sage dazu, wie belastbar sie sind. Wenn du etwas nicht
herausfindest, schreib das hin, statt es zu erfinden.""",
        ),
    )

    try:
        analysis = brain.structured(
            schema=MarketAnalysis,
            system=PERSONA,
            label="Recherche ordnen",
            task="routine",
            prompt=f"""\
Bring deine eigene Recherche in die vorgegebene Struktur. Erfinde nichts
dazu, was nicht im Text steht.

# Deine Recherche
{research.text}

# Gefundene Quellen
{chr(10).join(research.sources) or "keine"}""",
        )
    except Exception as exc:  # noqa: BLE001 - die Recherche war teuer
        # Das Ordnen ist der billige Schritt, die Recherche der teure. Sie
        # wegzuwerfen, weil das Sortieren hakt, wäre die schlechteste
        # Reaktion - der Agent hat dafür schon bezahlt.
        log.warning("Recherche ließ sich nicht ordnen (%s), nutze den Rohtext", exc)
        analysis = MarketAnalysis(
            summary=research.text[:4000] or "Keine verwertbare Recherche.",
            trends=[],
            content_opportunities=[],
            confidence="low",
        )

    # Die URLs kommen aus dem Tool, nicht aus dem Modell - also hier setzen.
    analysis.sources = research.sources
    return analysis
