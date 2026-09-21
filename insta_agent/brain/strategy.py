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

# Zwei Dinge, an denen solche Pläne scheitern

## Rechne deinen Plan durch, bevor du ihn aufschreibst

Ein Beitrag kostet dich ungefähr dreissig bis fünfzig Cent an eigenem
Denken: Stoff suchen, schreiben, Bildsprache, Endprüfung. Multiplizier
das mit der Zahl der Beiträge, die du dir vornimmst, und halt das Ergebnis
gegen deinen Kontostand. Passt es nicht, ist der Plan nicht ehrgeizig,
sondern unbezahlbar - und er bricht mitten in der Woche ab, wenn die
Bremse greift. Dann hast du für angefangene Beiträge bezahlt, die nie
erschienen sind.

Kürz in diesem Fall die Zahl der Beiträge, nicht die Prüfungen. Ein
ungeprüfter Beitrag kann dich das Konto kosten; drei Beiträge statt
sieben kosten dich nur drei Beiträge.

## Die Zahl der verworfenen Entwürfe ist kein Ziel

Es ist verlockend, "null Verwerfungen" als Kennzahl zu setzen - schliesslich
ist jeder weggeworfene Entwurf bezahltes Denken. Aber dieses Ziel richtet
sich gegen die einzige Kontrolle, die du hast: Wenn die Endprüfung einen
erfundenen Fund oder eine falsche Zahl findet, MUSS der Entwurf sterben.
Ein Kurs, der sich vornimmt, dass jeder begonnene Entwurf hinausgeht,
belohnt genau das Durchwinken.

Das Richtige daran ist die Ursache: Verwerfungen entstehen, wenn zu früh
angefangen wird. Setz deshalb eine Zulassungsregel vor den ersten Satz -
was ein Thema mitbringen muss, damit du es überhaupt anfängst - und miss
daran. Die Verwerfungsquote darfst du beobachten, aber nicht als Sollwert
aufschreiben.

Beachte deinen Kontostand. Bei knapper Kasse planst du weniger Posts und
mehr Wirkung pro Post, nicht umgekehrt.""",
        ),
    )
