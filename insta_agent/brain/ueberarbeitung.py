"""Einen beanstandeten Beitrag nachbessern, statt ihn wegzuwerfen.

Die Endprüfung findet Fehler - und dann? Bisher: nichts. Der Entwurf lag
mit einem roten Vermerk da, und wer ihn freigab, veröffentlichte die
falsche Zahl. Das ist die schlechteste aller Möglichkeiten: eine
Kontrolle, die etwas findet, aber nichts bewirkt.

Hier wird sie wirksam. Der Agent bekommt seinen eigenen Beitrag zurück,
Befund für Befund, und schreibt ihn neu. Nicht irgendeinen neuen Beitrag:
Der Gedanke soll stehenbleiben, wenn er zu retten ist. Ist er es nicht -
weil die Zahl, auf der alles stand, einfach falsch war -, dann darf und
soll der Agent das Thema wechseln, statt eine falsche Behauptung
umzuformulieren, bis sie durchgeht.
"""

from __future__ import annotations

import logging

from ..llm import Brain
from ..models import PostDraft, Pruefbericht
from .prompts import PERSONA, identity_block, strategy_block, with_context

log = logging.getLogger(__name__)


def _befunde_text(bericht: Pruefbericht) -> str:
    zeilen = []
    for b in bericht.beanstandet:
        zeilen.append(f'- "{b.behauptung}"\n  {b.urteil.upper()}: {b.begruendung}')
        if b.beleg:
            zeilen.append(f"  Fundstelle: {b.beleg}")
    if bericht.korrekturen:
        zeilen.append("\nVorgeschlagene Korrekturen:")
        zeilen.extend(f"- {k}" for k in bericht.korrekturen)
    return "\n".join(zeilen) or "(keine Einzelbefunde)"


def ueberarbeite_beitrag(
    brain: Brain,
    *,
    identity,
    strategy,
    draft: PostDraft,
    bericht: Pruefbericht,
    max_hashtags: int = 20,
    modell: str | None = None,
) -> PostDraft:
    """Schreibt den Beitrag neu, sodass jeder Befund erledigt ist."""
    neu = brain.structured(
        schema=PostDraft,
        system=PERSONA,
        label="Beitrag nachbessern",
        modell=modell,
        prompt=with_context(
            identity_block(identity),
            strategy_block(strategy),
            f"""\
# Dein Entwurf

## Text auf dem Bild
{draft.bildtext}

## Zweite Zeile
{draft.visual.subline}

## Weitere Zeilen
{chr(10).join(draft.visual.body_lines) or "(keine)"}

## Bildunterschrift
{draft.caption}

## Erster Kommentar
{draft.first_comment_prompt}

## Bildprompt
{draft.image_generation_prompt}""",
            f"""\
# Was die Endprüfung gefunden hat

{bericht.zusammenfassung}

{_befunde_text(bericht)}""",
            f"""\
# Auftrag
Schreib diesen Beitrag neu, sodass kein Befund mehr zutrifft.

Das ist keine Umformulierung. Eine falsche Zahl wird nicht weicher
formuliert, sondern ersetzt - durch die richtige, mit der Quelle, die sie
belegt. Wenn du die richtige Zahl nicht kennst, nimm sie nicht in den
Beitrag.

Trägt die Aussage nach der Korrektur nicht mehr - weil die Zahl, auf der
alles stand, falsch war -, dann schreib einen anderen Beitrag zum selben
Wochenziel. Ein schwacher Beitrag, der stimmt, ist besser als ein starker,
der nicht stimmt. Ein starker, der stimmt, ist besser als beide.

Achte darauf:
- Eine Quellenangabe nennt Veröffentlichung und Jahrgang, nicht nur eine
  Behörde.
- Jede Rechnung muss aufgehen. Rechne sie nach, bevor du sie hinschreibst.
- Was du nicht belegen kannst, kennzeichnest du als Annahme - oder lässt
  es weg.
- Der Text auf dem Bild und die Bildunterschrift müssen zueinander
  passen. Eine korrigierte Zahl in der Unterschrift nützt nichts, wenn im
  Bild die alte steht.

Höchstens {max_hashtags} Hashtags. Den Bildprompt darfst du behalten,
wenn er zum neuen Text noch passt - sonst schreib ihn mit.""",
        ),
    )

    log.info("Beitrag nachgebessert: %s", neu.bildtext[:60])
    return neu
