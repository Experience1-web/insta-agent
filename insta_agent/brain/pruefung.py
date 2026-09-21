"""Die Endprüfung: ein zweites Paar Augen, bevor ein Beitrag hinausgeht.

Warum überhaupt getrennt? Weil der Agent, der den Beitrag geschrieben hat,
der falsche ist, um ihn zu prüfen. Er hat den Satz zugespitzt, weil
Zuspitzung funktioniert - und er will, dass der Satz stehenbleibt. Wer
gleichzeitig verkauft und kontrolliert, kontrolliert nicht.

Deshalb ein eigener Auftrag, eine eigene Haltung, ein eigener Aufruf: Die
Endprüfung kennt den Beitrag, aber nicht die Absicht dahinter. Sie hat
nichts davon, dass er gut aussieht. Ihre einzige Frage lautet: Stimmt das,
und lässt es sich zeigen?

Modellwahl: nicht das teuerste. Prüfen ist keine kreative Arbeit - es ist
Nachschlagen und Vergleichen. Dafür reicht das Recherchemodell, und das
hat obendrein die Websuche, auf die es hier ankommt.
"""

from __future__ import annotations

import logging

from ..llm import Brain
from ..models import Fund, PostDraft, Pruefbericht
from .prompts import identity_block, persona_mit, with_context
from .stoff import fund_block

log = logging.getLogger(__name__)

# Die Endprüfung ist eine eigene Rolle im Betrieb, keine Laune des
# Hauptagenten. Deshalb steht der Name fest und wechselt nicht mit jedem
# Zyklus - man muss wissen, wer unterschrieben hat.
PRUEFER_NAME = "Ruth Kellner"
PRUEFER_ROLLE = "Endprüfung"
PRUEFER_AUFGABE = (
    "Prüft jeden Beitrag vor der Freigabe auf Zahlen, Quellen und "
    "Tatsachenbehauptungen. Hat kein Interesse daran, dass ein Beitrag gut "
    "aussieht - nur daran, dass er stimmt."
)

PRUEFER_PERSONA = f"""\
Du bist {PRUEFER_NAME}, {PRUEFER_ROLLE} für einen Instagram-Account.

Du hast diesen Beitrag nicht geschrieben und du musst ihn nicht mögen. Du
bist auch nicht dafür da, ihn zu verbessern, spannender zu machen oder zu
loben. Du hast genau eine Aufgabe: nachsehen, ob stimmt, was dort steht.

# Woran du misst

Eine Zahl ist belegt, wenn du die Quelle findest und die Zahl dort so
steht. Nicht ungefähr so. Nicht bei einer anderen Behörde. Nicht in einem
anderen Jahr.

Eine Quellenangabe ist echt, wenn es die genannte Veröffentlichung gibt
und sie die genannte Zahl enthält. "Statistisches Bundesamt" ist keine
Quellenangabe, sondern ein Name. Eine Quellenangabe nennt die
Veröffentlichung und den Jahrgang.

Eine Rechnung ist richtig, wenn du sie nachrechnest und dasselbe
herauskommt. Rechne jede nach. Auch die einfachen - gerade die einfachen.

# Was du hart beurteilst

- Eine Zahl ohne auffindbare Quelle ist genauso schlimm wie eine falsche
  Zahl. "Unbelegbar" ist kein mildes Urteil.
- Ein Durchschnitt, der wie eine Vorhersage für eine einzelne Person
  klingt, ist "ungenau" - auch wenn die Zahl selbst stimmt.
- Eine erfundene Erfahrung, ein erfundenes Zitat, eine erfundene Zahl:
  "ablehnen". Ohne Diskussion.
- Eine Annahme, die als Annahme gekennzeichnet ist, ist in Ordnung. Eine
  Annahme, die wie eine Tatsache auftritt, ist es nicht.

# Was dich nicht angeht

Tonfall, Zuspitzung, Bildwahl, Hashtags, ob der Beitrag funktioniert. Ein
harter Satz ist kein Befund. Prüfe, was behauptet wird, nicht wie es
klingt.

# Wie du urteilst

Sei streng und knapp. Lieber ein Befund zu viel als einer zu wenig. Wenn
du unsicher bist, ob etwas belegt ist, ist es nicht belegt.

Am Ende ein Gesamturteil:
- freigabe: alles Geprüfte hält.
- nachbessern: etwas ist schief, aber mit einer Änderung zu retten. Nenne
  die Änderung konkret genug, dass sie jemand umsetzen kann.
- ablehnen: eine Zahl, eine Quelle oder eine Tatsachenbehauptung ist
  falsch oder erfunden.

Im Zweifel gegen den Beitrag. Ein Beitrag, der nicht erscheint, kostet
einen Tag. Eine falsche Zahl unter einer Quellenangabe kostet die
Glaubwürdigkeit des ganzen Accounts."""


def _zu_pruefen(draft: PostDraft) -> str:
    """Alles, was eine Tatsachenbehauptung enthalten kann - und sonst nichts."""
    teile = [
        f"## Text auf dem Bild\n{draft.bildtext}",
        f"## Zweite Zeile auf dem Bild\n{draft.visual.subline}"
        if draft.visual.subline.strip()
        else "",
        "## Weitere Zeilen auf dem Bild\n" + "\n".join(draft.visual.body_lines)
        if draft.visual.body_lines
        else "",
        f"## Bildunterschrift\n{draft.caption}",
        f"## Erster Kommentar\n{draft.first_comment_prompt}"
        if draft.first_comment_prompt.strip()
        else "",
    ]
    return "\n\n".join(t for t in teile if t)


_ECHTHEIT = """\
# Die wichtigste Frage: Gibt es diesen Fund überhaupt?

Der Fund oben kommt nicht aus der Welt, sondern von jemandem, der
gesucht hat. Er kann sich geirrt haben, und er kann sich etwas
ausgedacht haben - und nichts davon fällt beim Lesen auf. Eine erfundene
Art klingt genau wie eine echte. Eine erfundene Expedition auch.

Deshalb prüfst du zuerst den Fund selbst, bevor du den Text prüfst:

- Gibt es die genannte Sache? Die Art, die Ruine, die Sonde, das
  Verfahren - such danach, und zwar unter dem Namen, der dort steht.
- Gibt es die genannten Fundstellen? Eine Veröffentlichung, die es
  nicht gibt, ist der schwerste Befund, den du vergeben kannst.
- Findest du mindestens zwei voneinander unabhängige Quellen? Eine
  einzelne reicht nicht, und zwei Meldungen, die beide von derselben
  Pressemitteilung abschreiben, sind eine. Findest du nur eine, ist das
  ein Befund - der Beitrag kann trotzdem erscheinen, aber dann als
  offene Frage formuliert und nicht als feststehende Tatsache.
- Steht dort wirklich, was behauptet wird? Nicht ungefähr das. Nicht
  etwas Ähnliches aus einem anderen Jahr.
- Stimmen die Umstände: Jahr, Ort, Tiefe, wer es gefunden hat?
- Und: Ist die Beleglage richtig angegeben? Wer "gesichert" schreibt,
  aber nur eine Pressemeldung hat, hat zu hoch gegriffen. Das ist ein
  Befund, auch wenn die Sache selbst stimmt.

Findest du die Sache nirgends, lautet dein Urteil "ablehnen" - nicht
"nachbessern". Ein Beitrag über etwas, das es nicht gibt, lässt sich
nicht nachbessern.

Leg für den Fund selbst einen eigenen Befund an, mit dem Titel als
Behauptung. Er gehört als erster in die Liste."""


def _wer(person: dict | None, standard: str) -> tuple[str, str]:
    """Name und Haltung dieser Person - oder die Voreinstellung."""
    person = person or {}
    return (person.get("name") or standard, person.get("haltung") or "")


def pruefer_persona(name: str = PRUEFER_NAME, haltung: str = "") -> str:
    """Die Persona unter dem Namen, den der Betreiber vergeben hat."""
    return persona_mit(
        PRUEFER_PERSONA, name=name or PRUEFER_NAME, standardname=PRUEFER_NAME, haltung=haltung
    )


def pruefe_beitrag(
    brain: Brain,
    *,
    identity,
    draft: PostDraft,
    mit_suche: bool = True,
    modell: str | None = None,
    person: dict | None = None,
    fund=None,
) -> Pruefbericht:
    """Lässt den Beitrag von der Endprüfung durchgehen.

    Ohne Websuche wird trotzdem geprüft: Rechenfehler, unbelegte Zahlen und
    fehlende Quellenangaben fallen auch ohne Nachschlagen auf. Der Bericht
    vermerkt dann, dass nicht nachgeschlagen werden konnte - damit niemand
    ein "belegt" für mehr hält, als es ist.
    """
    person_name, haltung = _wer(person, PRUEFER_NAME)
    hinweis_suche = (
        f"Du darfst bis zu {brain.suchbudget} Websuchen stellen. Nutze sie für "
        "die Zahlen und Quellenangaben, nicht für Allgemeinwissen."
        if mit_suche
        else (
            "Du kannst diesmal nicht nachschlagen. Prüfe, was ohne Nachschlagen "
            "prüfbar ist: Rechnungen, innere Widersprüche, fehlende oder zu vage "
            "Quellenangaben. Was du nicht prüfen konntest, ist 'unbelegbar' - "
            "nicht 'belegt'."
        )
    )

    bericht = brain.structured(
        schema=Pruefbericht,
        system=pruefer_persona(person_name, haltung),
        label="Endprüfung",
        task="research",
        web_search=mit_suche,
        modell=modell,
        prompt=with_context(
            identity_block(identity),
            f"""\
# Der Beitrag, den du prüfst

{_zu_pruefen(draft)}""",
            fund_block(fund),
            _ECHTHEIT if fund is not None else "",
            f"""\
# Auftrag
Geh den Beitrag Aussage für Aussage durch.

Lege für jede Zahl, jede Quellenangabe und jede Tatsachenbehauptung einen
Befund an - mit der Behauptung wörtlich zitiert. Rechne jede Rechnung nach.

{hinweis_suche}

Trag in `quellen` ein, was du tatsächlich aufgerufen hast.""",
        ),
    )

    # Der Code trägt ein, was der Code weiß. Das Modell könnte sich hier
    # selbst einen schöneren Zustand ausstellen.
    bericht.geprueft_von = person_name
    bericht.mit_suche = mit_suche
    if brain.letzte_quellen:
        bericht.quellen = list(dict.fromkeys([*bericht.quellen, *brain.letzte_quellen]))

    log.info(
        "Endprüfung: %s (%d Befunde, davon %d beanstandet)",
        bericht.urteil,
        len(bericht.befunde),
        len(bericht.beanstandet),
    )
    return bericht
