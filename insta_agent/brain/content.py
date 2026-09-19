"""Post-Erstellung: Caption, Hashtags und der Bauplan fürs Bild."""

from __future__ import annotations

from ..llm import Brain
from ..models import PostDraft
from .prompts import PERSONA, identity_block, strategy_block, with_context

MAX_CAPTION = 2200


def create_post_draft(
    brain: Brain,
    *,
    identity,
    strategy,
    recent_captions: list[str],
    max_hashtags: int,
    performance_note: str = "",
) -> PostDraft:
    already_used = (
        "\n".join(f"- {c[:120]}" for c in recent_captions)
        if recent_captions
        else "Noch nichts veröffentlicht - das hier wird dein erster Post."
    )

    draft = brain.structured(
        schema=PostDraft,
        system=PERSONA,
        label="Post schreiben",
        prompt=with_context(
            identity_block(identity),
            strategy_block(strategy),
            f"# Deine letzten Posts, wiederhole dich nicht\n{already_used}",
            f"# Was deine Zahlen sagen\n{performance_note}" if performance_note else "",
            f"""\
# Auftrag
Schreibe den nächsten Post. Er zahlt auf dein Wochenziel ein.

Der Hook sind die ersten rund 80 Zeichen - mehr sieht niemand, bevor er auf
"mehr" tippt. Wenn der Hook nicht trägt, ist der Rest egal. Keine Frage
als Hook, die man mit ja oder nein abnicken kann.

Die Caption gibt etwas Konkretes her: eine Beobachtung, eine Zahl, einen
Schritt, den jemand heute gehen kann. Allgemeinplätze werden nicht
geteilt, und geteilt zu werden ist dein einziger Wachstumsweg.

Hashtags: höchstens {max_hashtags}, ohne Raute. Misch bewusst - ein paar
große für Volumen, mehr mittlere, und einige kleine, spitze, in denen du
tatsächlich sichtbar bleibst. Reine Reichweiten-Tags ohne Bezug zum Inhalt
schaden dir.

Das Bild entsteht rein typografisch: Farbfläche, eine starke Zeile, dazu
optional wenige Stützzeilen. Halte die Headline unter 60 Zeichen, sonst
wird sie im Feed unleserlich. Die Farben wählst du aus deiner Bildsprache
und achtest auf harten Kontrast zwischen Text und Hintergrund.

Die Caption darf höchstens {MAX_CAPTION} Zeichen haben.""",
        ),
    )

    # Harte Grenzen der Plattform durchsetzen, statt auf das Modell zu hoffen.
    draft.hashtags = [h.lstrip("#").strip() for h in draft.hashtags if h.strip()][:max_hashtags]
    if len(draft.caption) > MAX_CAPTION:
        draft.caption = draft.caption[: MAX_CAPTION - 1].rstrip() + "…"
    return draft
