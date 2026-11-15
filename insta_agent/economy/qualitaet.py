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


# Die Notbremse je Zyklus muss einen ganzen Beitrag tragen. Mit Fable
# kostet er 3 bis 4 USD; bei der üblichen Grenze von gut 2 USD brach der
# erste Versuch nach dem Schreiben ab - bezahlt, aber ohne Prüfung.
QUALI_ZYKLUSGRENZE = 6.0


def quali_config(llm):
    """Die Einstellungen fürs Modell, wie sie im Qualitätsmodus gelten.

    Das Modell selbst wird hier nicht umgestellt: Die Arbeit am Beitrag
    holt sich Fable über die Rollen (Stoffsuche, Schreiben, Prüfung,
    Schlussredaktion). Reflexion, Strategie und Vorbilder bleiben beim
    gewohnten Modell - beim ersten Versuch kosteten sie auf Fable fast
    einen Dollar, ohne den Beitrag besser zu machen.
    """
    return replace(
        llm,
        effort=QUALI_AUFWAND,
        research_effort=QUALI_AUFWAND,
        max_web_searches=max(llm.max_web_searches, QUALI_SUCHEN),
    )


__all__ = ["KEY_QUALITAET", "QUALI_MODELL", "QUALI_ZYKLUSGRENZE", "quali_config"]
