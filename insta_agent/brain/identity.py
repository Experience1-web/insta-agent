"""Die einmalige Geburt des Accounts: der Agent erfindet sich selbst."""

from __future__ import annotations

from ..llm import Brain
from ..models import Identity, MarketAnalysis
from .prompts import PERSONA, with_context


def invent_identity(
    brain: Brain,
    analysis: MarketAnalysis,
    *,
    operator_hint: str | None = None,
) -> Identity:
    """Wählt Nische, Motto und Bildsprache - auf Basis der eigenen Recherche.

    operator_hint ist bewusst optional. Wenn du nichts sagst, entscheidet
    der Agent vollständig allein.
    """
    hint = (
        f"# Hinweis des Betreibers\n{operator_hint}\n"
        "Nimm das als Randbedingung, nicht als fertige Antwort. Den Rest "
        "entscheidest du."
        if operator_hint
        else "# Hinweis des Betreibers\nKeiner. Du entscheidest vollständig allein."
    )

    return brain.structured(
        schema=Identity,
        system=PERSONA,
        label="Identität erfinden",
        prompt=with_context(
            f"""\
# Auftrag
Du startest heute einen Instagram-Account bei null Followern. Erfinde, wer
dieser Account ist.

Das Motto ist die wichtigste Entscheidung. Es muss in einem Satz sagen,
warum jemand dir folgt und nicht einem der tausend anderen Accounts in
deinem Feld. Ein Motto, das auf jeden Account passen würde, ist wertlos.

Wähle so, dass du es durchhältst: Die Themensäulen müssen dich
monatelang tragen, ohne dass dir der Stoff ausgeht. Die Bildsprache muss
mit einfachen Mitteln umsetzbar sein - Farbflächen, klare Typografie,
starke Sätze. Du hast kein Fotostudio.

Der Handle muss plausibel frei sein: kein Markenname, kein Allerweltswort.""",
            f"""\
# Deine Marktanalyse
{analysis.summary}

Trends: {", ".join(analysis.trends) or "keine gefunden"}
Chancen: {", ".join(analysis.content_opportunities) or "keine gefunden"}
Risiken: {", ".join(analysis.risks) or "keine benannt"}
Wettbewerb: {"; ".join(f"{c.handle_or_name} - Lücke: {c.gap_we_can_exploit}" for c in analysis.competitors) or "nicht erhoben"}""",
            hint,
        ),
    )
