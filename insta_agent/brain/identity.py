"""Die einmalige Geburt des Accounts: der Agent erfindet sich selbst."""

from __future__ import annotations

from ..llm import Brain
from ..models import Identity, MarketAnalysis, NeueBildsprache
from .prompts import PERSONA, identity_block, with_context


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
- Die Bilder entstehen nach deiner Beschreibung, und sie sollen
  fotografisch sein: echtes Licht, echte Oberflächen, echte Tiefe.
  Kinoreif, nicht illustriert. Menschen dürfen darauf sein. Du hast
  damit jede Kamera, jedes Licht und jeden Ort zur Verfügung - nutze
  das, statt dich auf Farbflächen zurückzuziehen.
- Die eine Grenze: Ein Bild darf nie vorgeben, ein Beleg zu sein. Kein
  erfundener Bildschirmausschnitt einer Statistik, keine erfundene
  Urkunde, kein Diagramm, das aussieht wie aus einer Quelle. Keine
  erkennbare reale Person und nichts, was als Aufnahme eines
  tatsächlichen Ereignisses durchgeht. Inszeniert ja, dokumentarisch
  nein - so wie ein Titelbild im Magazin inszeniert ist, ohne zu lügen.
- Trotzdem muss es einen Grund geben, den Beitrag zu speichern oder
  weiterzuschicken. Ein schönes Bild allein wird angeschaut und
  weitergewischt. Es braucht eine Wendung, eine Erkenntnis, eine Reihe,
  etwas zum Wiederkommen. Reichweite ohne Bindung ist wertlos.
- Meide, was überfüllt ist. Generische KI-Kunst ohne Thema, beliebige
  Landschaften, Zitatkacheln vor Bildern: davon gibt es zehntausend.

In `visual_identity` beschreibst du deshalb nicht nur Farben, sondern den
wiedererkennbaren Bildaufbau: Motivwelt, Lichtführung, Objektiv und
Perspektive, Farbklima, Material und Körnung, und wo im Bild Platz für
Schrift bleibt. Jemand soll deine Beiträge im Feed erkennen, bevor er den
Namen liest.

Schreib sie so, dass ein Fotograf danach arbeiten könnte. "Dunkle
Farbflächen mit harter Typografie" ist keine Bildsprache, sondern der
Verzicht darauf.

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


BILDSPRACHE_AUFTRAG = """\
# Auftrag
Deine Bildsprache wird neu festgelegt. Alles andere bleibt: dein Name,
dein Motto, deine Nische, dein Tonfall, deine Themensäulen.

Was sich ändert: Deine Bilder sollen Fotografien sein. Echtes Licht,
echte Oberflächen, echte Tiefe - als hätte jemand mit einer Kamera in
einem Raum gestanden. Menschen dürfen darauf sein. Kinoreif, nicht
illustriert.

Der Maßstab ist die Titelstrecke eines Magazins, nicht "gut für
Instagram". Wenn du auf Farbflächen mit Typografie zurückfällst, hast du
die Aufgabe verfehlt: Dafür bräuchte es kein Bildmodell.

Die eine Grenze bleibt: Ein Bild darf nie vorgeben, ein Beleg zu sein.
Kein erfundener Statistik-Ausschnitt, keine Urkunde, kein Diagramm, keine
erkennbare reale Person, nichts, was als Aufnahme eines tatsächlichen
Ereignisses durchgeht. Inszeniert ja, dokumentarisch nein - so wie ein
Titelbild inszeniert ist, ohne zu lügen.

Schreib die neue Bildsprache so, dass ein Fotograf danach arbeiten
könnte: Motivwelt, Lichtführung, Objektiv und Standpunkt, Farbklima,
Material und Körnung, und wo im Bild die ruhige Fläche für die Schrift
liegt. Sie muss zu deiner Nische passen und über Monate durchzuhalten
sein."""


def erneuere_bildsprache(brain: Brain, identity: Identity) -> NeueBildsprache:
    """Lässt den Agenten seine Bildsprache neu schreiben - und nur die.

    Gebraucht, wenn sich die Möglichkeiten ändern: Als er sich seine
    Bildsprache gab, sollte er auf Fotorealismus verzichten. Diese
    Einschränkung ist gefallen, und einen ganzen Neuanfang ist sie nicht
    wert - Nische und Motto tragen ja.
    """
    return brain.structured(
        schema=NeueBildsprache,
        system=PERSONA,
        label="Bildsprache neu festlegen",
        prompt=with_context(identity_block(identity), BILDSPRACHE_AUFTRAG),
    )
