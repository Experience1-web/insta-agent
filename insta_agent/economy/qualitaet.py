"""Der Qualitätsmodus: jeder Beitrag mit dem stärksten Modell.

Das Gegenstück zum Sparmodus. Wo der Sparmodus Modell, Denkstufe und
Websuchen herunterschraubt, stellt der Qualitätsmodus alles nach oben:
Stoffsuche, Schreiben, Endprüfung, Nachbessern und Schlussredaktion
laufen auf Claude Fable 5.2, mit gründlichem Nachdenken und den vollen
Websuchen. Ein Beitrag kostet so etwa vier- bis fünfmal so viel wie im
Sparmodus - rund 2 bis 4 USD statt 0,50 bis 0,80.

Beide Schalter schließen einander aus: Wer den einen einschaltet,
schaltet den anderen ab.
"""

from __future__ import annotations

from dataclasses import replace

KEY_QUALITAET = "qualitaetsmodus"

QUALI_MODELL = "claude-fable-5-2"
QUALI_AUFWAND = "high"
QUALI_SUCHEN = 4


def quali_config(llm):
    """Die Einstellungen fürs Modell, wie sie im Qualitätsmodus gelten."""
    return replace(
        llm,
        model=QUALI_MODELL,
        research_model=QUALI_MODELL,
        effort=QUALI_AUFWAND,
        research_effort=QUALI_AUFWAND,
        max_web_searches=max(llm.max_web_searches, QUALI_SUCHEN),
    )


__all__ = ["KEY_QUALITAET", "QUALI_MODELL", "quali_config"]
