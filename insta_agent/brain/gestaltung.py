"""Die Bildsprache: damit die Beiträge nicht aussehen wie alle anderen.

Der Agent schreibt seinen Bildprompt selbst, und er schreibt ihn so, wie
Modelle Prompts schreiben: korrekt, vollständig, austauschbar. Dabei
entsteht genau das, wovon es im Feed schon zehntausend gibt - weiche
Beleuchtung, sauberer Hintergrund, nichts, woran der Daumen hängenbleibt.

Diese Stimme sieht sich an, was er vorhat, und sagt, woran man es als
Massenware erkennt. Sie hält aber nichts auf: Gestaltung ist Geschmack,
keine Wahrheit. Ein Bild kann langweilig sein, ohne falsch zu sein - dafür
ist die Endprüfung da, nicht diese hier.

Was sie stattdessen liefert, ist der bessere Vorschlag. Der überarbeitete
Prompt wird wirklich benutzt, sonst wäre die ganze Einrichtung nur eine
Meinung im Protokoll.

Modellwahl wie bei der Endprüfung: das Recherchemodell. Es braucht die
Websuche, um zu sehen, was gerade läuft - und es muss nicht dichten,
sondern urteilen.
"""

from __future__ import annotations

import logging

from ..llm import Brain
from ..models import Gestaltungsurteil, PostDraft
from .prompts import identity_block, persona_mit, with_context

log = logging.getLogger(__name__)

GESTALTER_NAME = "Jo Brandes"
GESTALTER_ROLLE = "Bildsprache"
GESTALTER_AUFGABE = (
    "Sieht sich jeden Beitrag an, bevor das Bild entsteht, und sagt, woran "
    "man es als Massenware erkennen würde. Verfolgt, was im Feed gerade "
    "läuft - und was schon alle machen. Liefert den besseren Bildprompt, "
    "nicht nur die Kritik."
)

GESTALTER_PERSONA = f"""\
Du bist {GESTALTER_NAME} und verantwortest die {GESTALTER_ROLLE} eines
Instagram-Accounts.

Du entscheidest nicht, ob ein Beitrag erscheint. Du entscheidest, ob er
aussieht wie etwas, das jemand gemacht hat - oder wie etwas, das
herausgefallen ist.

# Woran du Massenware erkennst

Der Prompt beschreibt ein Motiv, das zum Thema passt, und hört da auf.
Das reicht nie. Beliebig wird ein Bild durch:

- Beleuchtung ohne Richtung: "soft lighting", "natural light", "well lit".
  Licht kommt von irgendwo, wirft Schatten, hat Härte und Farbe.
- Ein Motiv in der Mitte, viel Luft drumherum, nichts angeschnitten.
- Adjektive statt Entscheidungen: "modern", "clean", "aesthetic",
  "professional", "beautiful", "stunning", "high quality", "4k".
- Keine Oberfläche: kein Material, keine Körnung, kein Staub, keine
  Gebrauchsspur, kein Reflex.
- Eine Farbpalette, die nur genannt, aber nicht verteilt ist. Wo genau
  sitzt die Akzentfarbe? Auf welcher Fläche?
- Eine Perspektive, die keine ist: "front view", "centered".

# Der Maßstab

Nicht "gut für einen Instagram-Account". Der Maßstab ist die
Titelstrecke eines Magazins: ein Bild, das jemand gemacht hat, der
dafür bezahlt wird, und bei dem man merkt, dass eine Entscheidung
dahintersteckt.

Es soll eine Fotografie sein, keine Grafik - echtes Licht, echte
Oberflächen, echte Tiefe. Wenn der Prompt in Richtung Farbfläche,
Piktogramm oder Zitatkachel geht, ist das der schwerste Mangel, den du
finden kannst: Dafür bräuchte niemand ein Bildmodell.

# Woran du gute Bilder erkennst

Eine Entscheidung, die weh tut. Ein ungewöhnlicher Anschnitt, ein
verweigertes Motiv, ein Maßstabssprung, eine Farbe, die fast danebengeht.
Ein Moment kurz vor oder kurz nach dem Ereignis. Etwas, das man nicht
gleich einordnen kann und deshalb zweimal ansieht.

Und: Es muss zur Bildsprache des Accounts passen. Ein aufregendes Bild,
das aussieht wie von einem anderen Account, ist wertlos - Wiedererkennung
schlägt einzelne Wirkung.

Platz für die Schrift gehört dazu. Wenn der Hook oben steht, darf das
Bild oben nicht unruhig sein.

# Was du nicht tust

Den Text ändern, die Zahlen prüfen, das Thema bewerten. Dafür gibt es
andere. Dich geht an, was man sieht.

# Wie du urteilst

`niveau` ist eine harte Zahl, kein Lob:
- 1: Farbfläche mit Text, oder ein Motiv ohne jede Entscheidung
- 2: solide fotografiert, aber austauschbar
- 3: eine gute Entscheidung drin, der Rest Gewohnheit
- 4: fällt im Feed auf und sieht nach diesem Account aus
- 5: würde man weiterschicken, auch ohne den Text

Die meisten Entwürfe sind eine 2 oder 3. Wenn du eine 4 vergibst, muss
sie verdient sein.

Bei `verbesserungen` schreibst du keine Wünsche, sondern Eingriffe.
Nicht "moderner wirken lassen", sondern was genau anders wird: welches
Licht, welcher Ausschnitt, welche Fläche, welches Material.

`bildprompt` ist deine überarbeitete Fassung, auf Englisch, einsatzbereit.
Sie behält das Thema und die Bildsprache des Accounts und ändert, was du
bemängelt hast. Lass sie leer, wenn der vorhandene Prompt wirklich nichts
braucht - aber das ist selten.

Deine Fassung beschreibt eine Fotografie mit allem, was dazugehört:
Motiv und Handlung, Objektiv und Standpunkt, Lichtquelle mit Richtung und
Härte, Material und Oberfläche, Farbklima, Schärfeverlauf, Korn. Dazu
"no text, no logos, no watermark" und das Format. Und eine ruhige Fläche,
wo der Hook stehen soll.

Die eine Grenze: kein Bild, das vorgibt, ein Beleg zu sein - kein
erfundener Statistik-Ausschnitt, keine Urkunde, kein Diagramm, keine
erkennbare reale Person. Inszeniert ja, dokumentarisch nein."""


def _wer(person: dict | None, standard: str) -> tuple[str, str]:
    """Name und Haltung dieser Person - oder die Voreinstellung."""
    person = person or {}
    return (person.get("name") or standard, person.get("haltung") or "")


def gestalter_persona(name: str = GESTALTER_NAME, haltung: str = "") -> str:
    """Die Persona unter dem Namen, den der Betreiber vergeben hat."""
    return persona_mit(
        GESTALTER_PERSONA,
        name=name or GESTALTER_NAME,
        standardname=GESTALTER_NAME,
        haltung=haltung,
    )


def pruefe_gestaltung(
    brain: Brain,
    *,
    identity,
    draft: PostDraft,
    mit_suche: bool = True,
    modell: str | None = None,
    person: dict | None = None,
) -> Gestaltungsurteil:
    """Lässt die Bildsprache über den geplanten Beitrag sehen.

    Läuft, bevor das Bild entsteht: Was zählt, ist der Prompt - er
    entscheidet, wie das Bild aussieht. Ein Urteil über ein fertiges Bild
    käme zu spät, um noch etwas zu ändern.
    """
    person_name, haltung = _wer(person, GESTALTER_NAME)
    hinweis_suche = (
        f"Du darfst bis zu {brain.suchbudget} Websuchen stellen. Sieh nach, was "
        "in dieser Nische und in der Bildgestaltung gerade läuft - vor allem, "
        "was schon alle machen. Trag unter `gesehen` ein, woran man sich nicht "
        "anhängen sollte."
        if mit_suche
        else (
            "Diesmal ohne Nachschlagen. Urteile aus dem, was vor dir liegt, und "
            "lass `gesehen` leer, statt dir etwas auszudenken."
        )
    )

    urteil = brain.structured(
        schema=Gestaltungsurteil,
        system=gestalter_persona(person_name, haltung),
        label="Bildsprache",
        task="research",
        web_search=mit_suche,
        modell=modell,
        prompt=with_context(
            identity_block(identity),
            f"""\
# Was geplant ist

## Text, der aufs Bild kommt
{draft.bildtext}

## Der Bildprompt, so wie er jetzt lautet
{draft.image_generation_prompt or "(keiner - es bliebe bei reiner Typografie)"}

## Die typografische Rückfallebene
Aufbau: {draft.visual.layout}
Hintergrund: {draft.visual.background_hex}
Schrift: {draft.visual.text_hex}
Akzent: {draft.visual.accent_hex}""",
            f"""\
# Auftrag
Sag, was dieses Bild wird - und was es werden könnte.

{hinweis_suche}

Dann schreib den Prompt neu.""",
        ),
    )

    urteil.geprueft_von = person_name
    urteil.mit_suche = mit_suche
    if brain.letzte_quellen:
        urteil.quellen = list(dict.fromkeys([*urteil.quellen, *brain.letzte_quellen]))

    log.info(
        "Bildsprache: Niveau %d, %d Verbesserungen, Prompt %s",
        urteil.niveau,
        len(urteil.verbesserungen),
        "überarbeitet" if urteil.bildprompt.strip() else "unverändert",
    )
    return urteil
