"""Post-Erstellung nach den drei Viralitätsregeln.

Reihenfolge der Aufmerksamkeit: Bild mit Hook-Text, erste Caption-Zeile,
Fließtext, Aufruf. Der erste Kommentar startet die Diskussion.

Geschrieben wird nicht über das, was gerade einfällt, sondern über den
Fund, den die Stoffsuche mitbringt. Der Unterschied ist der ganze
Account: Was einem einfällt, ist der eigene Alltag, und den hat der
Daumen schon.
"""

from __future__ import annotations

from ..llm import Brain
from ..models import Fund, PostDraft
from .prompts import PERSONA, identity_block, strategy_block, with_context
from .stoff import fund_block

# Der Auftrag fuer das Karussell. Steht getrennt, weil er der laengste
# einzelne Abschnitt ist - und weil er der ist, an dem sich entscheidet,
# ob jemand wischt oder weiterzieht.
KARUSSELL = """\
Ein Beitrag darf mehrere Bilder haben, durch die man wischt. Der Grund
ist die Bewegung: Wer wischt, bleibt - und wer bleibt, zaehlt bei
Instagram mehr als zehn, die vorbeiziehen. Aber man wischt nur weiter,
wenn man wissen will, wie es weitergeht.

**Die wichtigen Tatsachen werden auf die Bilder verteilt: eine je
Karte.** So will es der Betreiber, und das ist der Kern des Karussells.
Jede Karte traegt genau eine der wichtigen Tatsachen des Fundes - nicht
zwei, und keine Karte ohne eine.

**Aber nur die Tatsachen, die sich interessant anhoeren.** Nicht jede
belegte Tatsache verdient eine Karte. Such aus allem, was im Fund steht,
die heraus, bei denen jemand "echt jetzt?" sagt - und lass den Rest in
der Bildunterschrift. Die Probe fuer jede Karte: Wuerde jemand genau
diesen Satz beim Abendessen weitererzaehlen? "Die Koralle leuchtet nur,
wenn man sie beruehrt" - ja. "2025 wissenschaftlich beschrieben" - nein,
das ist ein Aktenvermerk. Wann etwas veroeffentlicht wurde, wie es
heisst und wer es beschrieben hat, ist fast nie die interessante
Tatsache, sondern der Beleg dafuer.

**Und die Reihenfolge erzaehlt eine Geschichte.** Dieselben Tatsachen in
beliebiger Reihenfolge sind ein Datenblatt; niemand wischt durch ein
Datenblatt. In der richtigen Reihenfolge ist jede Karte ein Schritt, und
jede macht Lust auf die naechste. Wer nur die Karten liest, ohne die
Bildunterschrift, muss am Ende die ganze Sache verstanden haben.

Die Reihenfolge, an der du dich orientierst - nicht jede Stufe braucht
eine Karte, aber keine steht an der falschen Stelle:

1. Das erste Bild: das Erstaunliche, in einem Satz (der Hook).
2. Was ist das ueberhaupt? In Alltagsworten - "eine neue Korallenart,
   so gross wie ein Fingernagel", nicht der lateinische Name.
3. Wo und wie wurde es gefunden? Ein Ort, den man sich vorstellen kann.
4. Das eine Detail, das es besonders macht - mit einem Vergleich, den
   jeder fuehlt.
5. Warum das wichtig ist oder was es veraendert. Oder die offene Frage,
   die bleibt.

**Jede Karte muss jemand verstehen, der nichts darueber weiss.** Dieselbe
Regel wie beim Hook, und sie gilt fuer jede Karte:
- Kein Fachwort ohne Uebersetzung. "Auf Reiz" versteht niemand, "wenn
  man sie beruehrt" jeder. "Zoantharie" gar nicht, "Krustenanemone"
  vielleicht, "eine Art Koralle" immer.
- Keine Zahl ohne Gefuehl dafuer. "515 Nanometer" ist fuer fast alle
  bedeutungslos - schreib "gruen". Eine Zahl bleibt, wenn sie ohne
  Erklaerung wirkt: "1.800 Jahre", "so tief wie der Mount Everest hoch".
- Ein lateinischer Name steht nie allein auf einer Karte. Er gehoert in
  die Bildunterschrift. "Corallizoanthus aureus, 2025 beschrieben" ist
  keine Karte, sondern eine Karteikarte.

**Wie viele, entscheidest du an der Geschichte.** Eine Karte gibt es
nur, wenn sie einen Schritt erzaehlt, den die anderen nicht erzaehlen.
Zwei bis vier sind ueblich; bei einer Sache, die in einem Satz gesagt
ist, gar keine. Lieber eine Karte weniger als eine, die nur da ist, um
die Zahl vollzumachen.

Der Fehler, den du nicht machen darfst: etwas erfinden. Jede Karte
sagt nur, was im Fund belegt ist - aber sie sagt es so, dass man es
versteht. Und keine wiederholt, was schon auf dem ersten Bild steht.

**Die Bilder zeigen die Sache, um die es geht.** Nicht ein Wort aus dem
Kartentext. Steht auf der Karte "aus einer Hoehle", ist das Bild keine
Treppe in einer Tropfsteinhoehle, sondern wieder die Koralle - oder ihr
Lebensraum unter Wasser. Ein Bild von etwas anderem macht aus dem
Beitrag ein Sammelsurium.

Unter `bildsuche` schreibst du deshalb, womit man ein Bild der Sache
selbst oder ihrer unmittelbaren Umgebung findet: zwei bis vier Woerter
auf Englisch, fuer jede Karte mit derselben Sache im Mittelpunkt.
Gibt es davon nichts - von einem Exoplaneten hat niemand ein Foto -,
laesst du es leer. Dann bekommt die Karte eine ruhige Schriftflaeche in
den Farben des Beitrags, und das ist besser als ein fremdes Bild.

**Die Karten muessen zusammen aussehen.** Wer wischt, soll merken, dass
er noch im selben Beitrag ist. In jedem `bildwunsch` also dieselbe
Lichtstimmung, dieselbe Farbwelt, dasselbe Objektiv und dieselbe
Anmutung wie im ersten Bild. Was sich aendert, ist der Blickwinkel auf
dieselbe Sache, nicht der Stil. Dieselben sieben Punkte wie beim ersten
Prompt, dasselbe "no text, no logos, no watermark", dieselbe ruhige
Flaeche fuer die Schrift.

`text` ist, was auf der Karte steht: hoechstens zehn Woerter, ohne
Punkt am Ende. `akzentwort` ist das Wort darin, auf das es ankommt -
eine Zahl, wenn eine da ist, sonst das tragende Wort."""


MAX_CAPTION = 2200
MAX_HOOK_WOERTER = 7

# Mit Fund ist das Thema gesetzt, ohne Fund muss er es selbst
# hochziehen - und beides braucht einen anderen Auftrag.
AUFTRAG_MIT_FUND = """\
# Auftrag
Schreib den Beitrag zu diesem Fund.

Das Thema steht damit fest, und du wechselst es nicht. Deine Arbeit ist
nicht, etwas Interessantes zu finden - das ist getan -, sondern es so zu
erzählen, dass jemand anhält. Der Fund trägt den Beitrag, deine Sätze
tragen den Fund.

Drei Dinge, an denen solche Beiträge scheitern:

- Du biegst die Sache zum Lebensratschlag. "Was diese Ruine uns über
  Neuanfänge lehrt" ist wieder Alltag, nur mit Kulisse. Lass die Sache
  die Sache sein.
- Du machst mehr daraus, als belegt ist. Der Fund ist erstaunlich genug.
  Steht dort `unbestaetigt`, schreibst du das hinein, statt es zu
  verschweigen - als offene Frage ist er immer noch stark.
- Du zeigst eine Metapher statt der Sache. Das Bild zeigt den Fund: den
  Ort, den Gegenstand, den Maßstab, den Moment. Die Bildidee der
  Stoffsuche ist dein Ausgangspunkt, nicht dein ganzer Prompt.

Das Detail, das anhält, gehört in die ersten Sekunden, nicht in den
letzten Absatz. Und irgendwo im Text steht in einem Satz, woher man das
weiß: Veröffentlichung, Jahr, Ort. Wer Erstaunliches behauptet, wird
nachgeschlagen - lieber lieferst du die Fundstelle gleich mit."""

AUFTRAG_OHNE_FUND = """\
# Auftrag
Schreibe den nächsten Beitrag. Er zahlt auf dein Wochenziel ein.

Diesmal kommt kein Fund von der Stoffsuche - such dir das Thema selbst.
Es gilt dieselbe Schwelle: etwas tatsächlich Geschehenes, das die meisten
noch nie gehört haben, und von dem es etwas zu sehen gibt. Kein Alltag,
keine Gewohnheiten, keine Lebensweisheit."""


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
    fund: Fund | None = None,
    persona: str | None = None,
) -> PostDraft:
    already_used = (
        "\n".join(f"- {c[:120]}" for c in recent_captions)
        if recent_captions
        else "Noch nichts veröffentlicht - das hier wird dein erster Post."
    )

    auftrag = AUFTRAG_MIT_FUND if fund is not None else AUFTRAG_OHNE_FUND

    draft = brain.structured(
        schema=PostDraft,
        system=persona or PERSONA,
        label="Post schreiben",
        prompt=with_context(
            identity_block(identity),
            strategy_block(strategy),
            fund_block(fund),
            f"# Deine letzten Posts, wiederhole dich nicht\n{already_used}",
            f"# Was deine Zahlen sagen\n{performance_note}" if performance_note else "",
            f"""\
{auftrag}

## image_generation_prompt - das Wichtigste an diesem Beitrag
Der Daumen bleibt wegen des Bildes stehen. Alles andere kommt danach.

Du beschreibst eine Fotografie, keine Grafik. Echtes Licht, echte
Oberflächen, echte Tiefe - als hätte jemand mit einer Kamera in einem
Raum gestanden. Menschen dürfen darauf sein.

Auf Englisch. Sieben Dinge gehören hinein, jedes als Entscheidung, nicht
als Adjektiv:

1. Motiv und Handlung - was ist zu sehen, und was passiert gerade
2. Objektiv und Standpunkt - Brennweite, Augenhöhe oder nicht, wie nah
3. Licht - woher, wie hart, welche Farbe, wohin die Schatten fallen
4. Material und Oberfläche - Stoff, Metall, Haut, Staub, Kratzer, Reflex
5. Farbklima - welche zwei, drei Farben das Bild beherrschen
6. Tiefe - was scharf ist und was nicht
7. Korn und Anmutung - Filmmaterial, Kontrastumfang, Kinolook

Abschluss: das Format 9:16.

"beautiful landscape" ist kein Prompt. "soft lighting" auch nicht - Licht
kommt immer von irgendwo. Sag woher.

Das Bild muss zwei Sekunden gewinnen: ein ungewöhnlicher Anschnitt, ein
Maßstabssprung, ein Moment kurz vor oder kurz nach dem Ereignis. Etwas,
das man nicht sofort einordnen kann.

Halte dich an deine Bildsprache, damit man den Beitrag im Feed erkennt,
bevor man den Namen liest.

Drei Regeln: Lass eine ruhige Fläche für die Schrift - oberes Drittel
oder Mitte. Schreib "no text, no logos, no watermark" hinein; die Schrift
kommt erst danach darüber. Und nichts, was vorgibt, ein Beleg zu sein:
kein Bildschirmausschnitt einer Statistik, keine Urkunde, kein Diagramm,
keine erkennbare reale Person.

## hook_text_on_screen
Die Zeile, die über dem Bild liegt. Höchstens {MAX_HOOK_WOERTER} Wörter.
Sie kämpft nicht mit dem Bild, sie dreht es: Sie sagt, was man beim
Hinsehen nicht sieht. Keine Bildunterschrift, keine Ankündigung ("So geht
X"), keine Frage, die man mit ja oder nein abnickt.

Und sie muss ohne jedes Vorwissen sofort verständlich sein. Wer die
Zeile im Vorbeiwischen liest, weiß nichts über das Thema - er hat eine
Sekunde. Deshalb:
- Nenn die Sache beim Namen, den jeder kennt: "Diese Koralle", "Ein
  Goldschatz", "Ein Stern". Kein "sie" oder "er", solange niemand weiß,
  wer gemeint ist.
- Kein Fachwort und keine Maßeinheit, die man erst nachschlagen muss.
  "515 Nanometer" sagt niemandem etwas, "leuchtet grün" jedem. Eine Zahl
  bleibt nur, wenn man sie ohne Erklärung fühlt: "1.800 Jahre", "7.902
  Meter tief".
- Gegenprobe: Würde jemand, der mit Wissenschaft nichts zu tun hat, den
  Satz jemandem weitererzählen können? Wenn nicht, ist er falsch.

Schlecht: "Bei Berührung antwortet sie mit 515 Nanometern".
Gut: "Diese Koralle leuchtet nur, wenn man sie berührt".

## hook (erste Caption-Zeile)
Die ersten rund 80 Zeichen der Bildunterschrift - mehr sieht niemand,
bevor er auf "mehr" tippt.

## body_text
Der Haupttext. Er wird nicht gelesen, er wird überflogen - also bau ihn
danach:

- Kurze Absätze, zwei bis drei Zeilen. Nie ein Block.
- Ein Emoji als Anker vor jedem Absatz, sparsam und passend. Kein
  Konfetti.
- Die tragenden Begriffe in GROSSBUCHSTABEN: die Zahl, der Name, das
  Maß, das eine Wort, auf das es ankommt. Wer nur die Hälfte liest, soll
  trotzdem wissen, worum es ging. Höchstens ein hervorgehobener Begriff
  je Absatz - sonst hebt sich nichts mehr ab.
- Ein Satz sagt, woher man es weiß: Veröffentlichung, Jahr, wer es
  gefunden hat.

Gib etwas Konkretes her. Allgemeinplätze werden weder gespeichert noch
geteilt.

## caption
Hook-Zeile und body_text zusammen, wie sie unter dem Beitrag stehen.
Höchstens {MAX_CAPTION} Zeichen.

## call_to_action
Dezent, aber bestimmt, und immer auf eine bestimmte Handlung gerichtet:
speichern, weiterschicken oder kommentieren. Ein Satz mit einem Grund
darin - nicht "folge mir", sondern warum genau dieser Beitrag es wert
ist, aufgehoben oder jemandem geschickt zu werden.

## hashtags
Höchstens {max_hashtags}, ohne Raute. Misch bewusst: ein paar große für
Volumen, mehr mittlere, einige kleine und spitze, in denen du tatsächlich
sichtbar bleibst. Reine Reichweiten-Tags ohne Bezug zum Inhalt schaden dir.

## first_comment_prompt
Eine offene Frage, die du selbst als ersten Kommentar setzt. Nicht mit ja
oder nein zu beantworten. Sie soll jemanden dazu bringen, von sich zu
erzählen - Kommentare sind das stärkste Signal, das du erzeugen kannst.

## visual
Der Bauplan für die Schrift auf dem Bild. Setz headline gleich dem
hook_text_on_screen, wähl Farben aus deiner Bildsprache und achte auf
harten Kontrast zwischen Text und Hintergrund. Derselbe Bauplan trägt
die Notfassung, falls kein Bild erzeugt wird.

`akzentwort` ist das eine Wort aus dem Hook, das farbig gesetzt wird.
Nimm das, woran die Sache hängt: die Zahl, die Tiefe, das Alter, den
Namen. Ein Wort, höchstens zwei - wer alles hervorhebt, hebt nichts
hervor. Es muss wörtlich so im Hook stehen, sonst findet es niemand.

## karten - die Bilder zum Durchwischen
{KARUSSELL}""",
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
