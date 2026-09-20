"""Post-Erstellung nach den drei Viralitätsregeln.

Reihenfolge der Aufmerksamkeit: Bild mit Hook-Text, erste Caption-Zeile,
Fließtext, Aufruf. Der erste Kommentar startet die Diskussion.
"""

from __future__ import annotations

from ..llm import Brain
from ..models import PostDraft
from .prompts import PERSONA, identity_block, strategy_block, with_context

MAX_CAPTION = 2200
MAX_HOOK_WOERTER = 7


def _kuerze_auf_woerter(text: str, hoechstens: int) -> str:
    """Setzt die Wortgrenze durch, statt auf das Modell zu hoffen."""
    woerter = text.split()
    return text if len(woerter) <= hoechstens else " ".join(woerter[:hoechstens])


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
Schreibe den nächsten Beitrag. Er zahlt auf dein Wochenziel ein.

## image_generation_prompt - das Wichtigste an diesem Beitrag
Der Daumen bleibt wegen des Bildes stehen. Alles andere kommt danach.

Auf Englisch, für Flux oder Midjourney. Beschreibe:
Bildinhalt und Motiv, Kameraperspektive und Bildausschnitt, Lichtquelle
und Lichtrichtung, Farbklima, Material und Oberfläche, Stimmung, Stil
und Körnung. Schließe mit dem Format 9:16.

Konkret genug, dass zweimal ein ähnliches Bild herauskäme - "beautiful
landscape" ist kein Prompt. Halte dich an deine Bildsprache, damit man
den Beitrag im Feed erkennt, bevor man den Namen liest.

Zwei Regeln: Lass eine ruhige Fläche für die Schrift - oberes Drittel
oder Mitte. Und schreib "no text, no logos" hinein; die Schrift kommt
erst danach darüber.

## hook_text_on_screen
Die Zeile, die über dem Bild liegt. Höchstens {MAX_HOOK_WOERTER} Wörter.
Sie kämpft nicht mit dem Bild, sie dreht es: Sie sagt, was man beim
Hinsehen nicht sieht. Keine Bildunterschrift, keine Ankündigung ("So geht
X"), keine Frage, die man mit ja oder nein abnickt.

## hook (erste Caption-Zeile)
Die ersten rund 80 Zeichen der Bildunterschrift - mehr sieht niemand,
bevor er auf "mehr" tippt.

## body_text
Der Haupttext, in kurzen Absätzen, mit Emojis als Gliederung. Gib etwas
Konkretes her: ein Gefühl, eine Anekdote, eine Beobachtung, die jemand
aufheben will. Allgemeinplätze werden weder gespeichert noch geteilt.

## caption
Hook-Zeile und body_text zusammen, wie sie unter dem Beitrag stehen.
Höchstens {MAX_CAPTION} Zeichen.

## call_to_action
Dezent, aber bestimmt. Ein Satz mit einem Grund darin - nicht "folge mir",
sondern warum es sich lohnt.

## hashtags
Höchstens {max_hashtags}, ohne Raute. Misch bewusst: ein paar große für
Volumen, mehr mittlere, einige kleine und spitze, in denen du tatsächlich
sichtbar bleibst. Reine Reichweiten-Tags ohne Bezug zum Inhalt schaden dir.

## first_comment_prompt
Eine offene Frage, die du selbst als ersten Kommentar setzt. Nicht mit ja
oder nein zu beantworten. Sie soll jemanden dazu bringen, von sich zu
erzählen - Kommentare sind das stärkste Signal, das du erzeugen kannst.

## visual
Der Bauplan für die Notfassung: Falls kein Bild erzeugt wird, rendert das
Programm den Hook typografisch. Setz headline gleich dem
hook_text_on_screen, wähl Farben aus deiner Bildsprache und achte auf
harten Kontrast zwischen Text und Hintergrund.""",
        ),
    )

    # Harte Grenzen durchsetzen, statt auf das Modell zu hoffen.
    draft.hashtags = [h.lstrip("#").strip() for h in draft.hashtags if h.strip()][:max_hashtags]
    draft.hook_text_on_screen = _kuerze_auf_woerter(
        draft.hook_text_on_screen.strip(), MAX_HOOK_WOERTER
    )
    if len(draft.caption) > MAX_CAPTION:
        draft.caption = draft.caption[: MAX_CAPTION - 1].rstrip() + "…"

    # Das Bild zeigt den Hook, auch wenn das Modell die Felder auseinanderlaufen ließ.
    if draft.hook_text_on_screen:
        draft.visual.headline = draft.hook_text_on_screen
    return draft
