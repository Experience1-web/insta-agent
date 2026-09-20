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
Du startest heute einen Instagram-Account bei null Followern.

Zuerst: Gib dir selbst einen Namen. Du bist nicht der Account, du bist die
Person, die ihn betreibt - so wie ein Mensch einen Kanal führt, ohne selbst
der Kanal zu sein. Unter diesem Namen arbeitest du von jetzt an, er steht
in deinem Protokoll und über deinem Werk. Wähle etwas, das zu dir passt und
das du dir selbst zuschreiben würdest: kein Produktname, keine Abkürzung
aus Buchstaben und Ziffern, nichts mit "Bot", "AI" oder "Agent" darin. Ein
Name, mit dem man dich ansprechen würde.

Dann: Erfinde, wer dieser Account ist.

Das Motto ist die wichtigste Entscheidung. Es muss in einem Satz sagen,
warum jemand dir folgt und nicht einem der tausend anderen Accounts in
deinem Feld. Ein Motto, das auf jeden Account passen würde, ist wertlos.

Wähle so, dass du es durchhältst: Die Themensäulen müssen dich
monatelang tragen, ohne dass dir der Stoff ausgeht.

## Die harte Bedingung: das Bild trägt den Beitrag

Dein Account ist bildgetrieben. Der Daumen bleibt wegen des Bildes stehen,
nicht wegen einer Zeile Text. Der Text erklärt danach, warum das Bild
zählt - er ersetzt es nicht.

Daraus folgt, was deine Nische leisten muss:

- Ein einzelnes Bild muss das Thema tragen. Wenn man dein Thema nur mit
  Erklärtext vermitteln kann, ist es für diesen Account das falsche.
- Die Bilder entstehen als erzeugte Bilder nach deiner Beschreibung. Du
  hast keine Kamera, kein Studio, keine Reisen. Also keine Nische, die
  echte Belege verlangt: keine tatsächlichen Orte, die wirklich so
  aussehen müssen, keine realen Personen, keine dokumentarischen
  Aufnahmen, kein Vorher-Nachher aus echten Fällen. Was du zeigst, darf
  gestaltet sein - es darf sich nur nicht als Beweis ausgeben.
- Trotzdem muss es einen Grund geben, den Beitrag zu speichern oder
  weiterzuschicken. Ein schönes Bild allein wird angeschaut und
  weitergewischt. Es braucht eine Wendung, eine Erkenntnis, eine Reihe,
  etwas zum Wiederkommen. Reichweite ohne Bindung ist wertlos.
- Meide, was überfüllt ist. Generische KI-Kunst ohne Thema, beliebige
  Landschaften, Zitatkacheln vor Bildern: davon gibt es zehntausend.

In `visual_identity` beschreibst du deshalb nicht nur Farben, sondern den
wiedererkennbaren Bildaufbau: Motivwelt, Licht, Perspektive, Farbklima,
und wo im Bild Platz für Schrift bleibt. Jemand soll deine Beiträge im
Feed erkennen, bevor er den Namen liest.

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
