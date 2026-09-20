"""Wer hier arbeitet - und womit.

Der Betrieb besteht nicht aus einem Agenten, sondern aus vier Rollen mit
verschiedenen Aufträgen: Einer sucht den Stoff, einer schreibt, einer
sieht auf die Gestaltung, einer prüft. Diese Trennung ist der ganze Sinn
der Sache - wer schreibt, prüft nicht, und wer prüft, gestaltet nicht.

Die Stoffsuche steht bewusst vor dem Schreiben. Wer schreibt, nimmt das
Thema, das ihm gerade einfällt, und was einem einfällt, ist der eigene
Alltag. Dagegen hilft kein besserer Satz, sondern nur ein besserer
Fund.

Hier steht, wer das ist, was ihn ausmacht, wie er aussieht und mit
welchem Modell er arbeitet. Die Modellwahl ist bewusst nicht fest
verdrahtet: Welches Modell für eine Rolle reicht, hängt davon ab, wie gut
die Ergebnisse sind und wie viel Geld da ist - das gehört dem Betreiber
in die Hand, nicht in den Quelltext.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .brain import (
    GESTALTER_AUFGABE,
    GESTALTER_NAME,
    GESTALTER_ROLLE,
    PRUEFER_AUFGABE,
    PRUEFER_NAME,
    PRUEFER_ROLLE,
    STOFF_AUFGABE,
    STOFF_NAME,
    STOFF_ROLLE,
)

# Wo die Modellwahl des Betreibers liegt.
KEY_MODELLWAHL = "modellwahl"
# Und wo seine Änderungen an den Steckbriefen liegen: Name, Aufgabe,
# Eigenschaften, Haltung und Aussehen. Der Quelltext gibt nur vor, womit
# angefangen wird.
KEY_MANNSCHAFT = "mannschaft"

# Was sich an einer Person ändern lässt. Alles andere - der Schlüssel,
# die Aufgabenstufe, wann sie drankommt - gehört zum Aufbau des Betriebs
# und nicht in ein Formular.
FELDER = ("name", "rolle", "aufgabe", "eigenschaften", "haltung", "bildwunsch")


@dataclass(frozen=True, slots=True)
class Rolle:
    schluessel: str
    name: str
    rolle: str
    aufgabe: str
    eigenschaften: tuple[str, ...]
    """Was diese Person ausmacht - drei bis fünf Stichworte, kein Lebenslauf."""

    aufgabenstufe: str
    """Welche Modellklasse voreingestellt ist: reasoning, research, routine."""

    bildwunsch: str
    """Wie diese Person sich selbst sehen würde, als Bildbeschreibung."""

    rang: str = "mitarbeiter"
    abschaltbar: str | None = None
    """Name der Einstellung, mit der sich die Rolle abschalten lässt."""

    steuert: tuple[str, ...] = field(default_factory=tuple)


# Der Chef bekommt Namen und Auftrag aus der Identität, die er sich selbst
# gegeben hat - deshalb stehen die hier leer und werden später gefüllt.
CHEF = Rolle(
    schluessel="chef",
    name="",
    rolle="Projektleitung",
    aufgabe="",
    eigenschaften=(
        "entscheidet allein",
        "zugespitzt, nie erfunden",
        "denkt in Wochenzielen",
        "trägt die Kasse",
    ),
    aufgabenstufe="reasoning",
    bildwunsch=(
        "a composed portrait of a person in their late thirties, direct gaze "
        "into the lens, plain dark studio background, one hard key light from "
        "the left leaving half the face in shadow, muted colour, fine film "
        "grain, shot on 85mm, editorial magazine portrait, serious but not cold"
    ),
    rang="chef",
)

STOFF = Rolle(
    schluessel="stoff",
    name=STOFF_NAME,
    rolle=STOFF_ROLLE,
    aufgabe=STOFF_AUFGABE,
    eigenschaften=(
        "sucht, bevor jemand schreibt",
        "verwirft Alltag ohne Nachsicht",
        "will die Fundstelle sehen",
        "misst am Daumen, nicht am Geschmack",
    ),
    aufgabenstufe="research",
    bildwunsch=(
        "a portrait of a person who hunts down stories for a living, leaning "
        "forward slightly, alert and amused, cluttered archive shelves far out "
        "of focus behind, warm low sun raking in from a window on the left, "
        "one bright accent in the clothing, 50mm, shallow depth of field, "
        "reportage portrait, curious rather than polished"
    ),
    abschaltbar="stoff_noetig",
)

BILDSPRACHE = Rolle(
    schluessel="bildsprache",
    name=GESTALTER_NAME,
    rolle=GESTALTER_ROLLE,
    aufgabe=GESTALTER_AUFGABE,
    eigenschaften=(
        "sieht zuerst die Form",
        "hasst Beliebigkeit",
        "kennt, was schon alle machen",
        "liefert den besseren Vorschlag",
    ),
    aufgabenstufe="research",
    bildwunsch=(
        "a portrait of a person with an art-director's eye, head slightly "
        "turned away, looking past the camera, plain concrete wall "
        "background, cool daylight from a large window on the right, one "
        "strong colour accent in the clothing, shallow depth of field, 50mm, "
        "contemporary design-studio portrait, quietly confident"
    ),
    abschaltbar="gestaltung_noetig",
)

ENDPRUEFUNG = Rolle(
    schluessel="pruefung",
    name=PRUEFER_NAME,
    rolle=PRUEFER_ROLLE,
    aufgabe=PRUEFER_AUFGABE,
    eigenschaften=(
        "rechnet jede Rechnung nach",
        "im Zweifel gegen den Beitrag",
        "unbestechlich unhöflich",
        "kein Interesse am schönen Schein",
    ),
    aufgabenstufe="research",
    bildwunsch=(
        "a portrait of a person who checks things for a living, arms folded, "
        "level unimpressed gaze straight at the lens, neutral grey background, "
        "even flat lighting with almost no shadow, desaturated palette, sharp "
        "focus edge to edge, 85mm, documentary portrait, entirely unsentimental"
    ),
    abschaltbar="pruefung_noetig",
)

# Die Reihenfolge ist die Reihenfolge der Arbeit: erst der Fund, dann
# der Text, dann das Bild, dann die Prüfung.
ROLLEN: tuple[Rolle, ...] = (CHEF, STOFF, BILDSPRACHE, ENDPRUEFUNG)
NACH_SCHLUESSEL = {r.schluessel: r for r in ROLLEN}


def standardmodell(rolle: Rolle, llm) -> str:
    """Welches Modell diese Rolle bekommt, solange niemand etwas umstellt."""
    if rolle.aufgabenstufe == "research":
        return llm.research_model
    if rolle.aufgabenstufe == "routine":
        return llm.cheap_model
    return llm.model


def modell_fuer(schluessel: str, wahl: dict | None, llm) -> str:
    """Das Modell einer Rolle: die Wahl des Betreibers, sonst die Voreinstellung."""
    gewaehlt = (wahl or {}).get(schluessel)
    rolle = NACH_SCHLUESSEL.get(schluessel)
    if rolle is None:
        return llm.model
    return gewaehlt or standardmodell(rolle, llm)


def person(schluessel: str, anpassung: dict | None = None, identitaet=None) -> dict:
    """Wie diese Person aussieht, nachdem der Betreiber drübergegangen ist.

    Die Voreinstellung steht im Quelltext, die Änderung im Speicher. Was
    der Betreiber nicht angefasst hat, bleibt, wie es war - deshalb wird
    gemischt und nicht ersetzt.
    """
    rolle = NACH_SCHLUESSEL.get(schluessel)
    eigen = (anpassung or {}).get(schluessel) or {}

    if schluessel == "chef" and identitaet is not None:
        # Name und Motto des Chefs stehen in seiner Identität. Sie dort
        # zu ändern ist richtig: Unter diesem Namen schreibt er, und mit
        # diesem Motto arbeitet er.
        grund = {"name": identitaet.agent_name, "aufgabe": identitaet.motto}
    elif rolle is not None:
        grund = {"name": rolle.name, "aufgabe": rolle.aufgabe}
    else:
        grund = {"name": "", "aufgabe": ""}

    if rolle is not None:
        grund["rolle"] = rolle.rolle
        grund["eigenschaften"] = list(rolle.eigenschaften)
        grund["bildwunsch"] = rolle.bildwunsch
    grund["haltung"] = ""

    for feld in FELDER:
        wert = eigen.get(feld)
        if wert not in (None, "", []):
            grund[feld] = wert
    return grund


def aufstellung(
    identitaet, settings, wahl: dict | None = None, anpassung: dict | None = None
) -> list[dict]:
    """Die Mannschaft, wie das Dashboard sie zeigt.

    Ohne Identität fehlt der Chef - dann steht der Betrieb noch nicht, und
    die übrigen Rollen warten.
    """
    leute: list[dict] = []
    for rolle in ROLLEN:
        if rolle.schluessel == "chef" and identitaet is None:
            continue
        eigen = person(rolle.schluessel, anpassung, identitaet)

        aktiv = True
        if rolle.abschaltbar:
            aktiv = bool(getattr(settings.posting, rolle.abschaltbar, True))

        leute.append(
            {
                "schluessel": rolle.schluessel,
                "name": eigen["name"],
                "rolle": eigen["rolle"],
                "aufgabe": eigen["aufgabe"],
                "eigenschaften": list(eigen["eigenschaften"]),
                "haltung": eigen["haltung"],
                "bildwunsch": eigen["bildwunsch"],
                "rang": rolle.rang,
                "modell": modell_fuer(rolle.schluessel, wahl, settings.llm),
                "standard": standardmodell(rolle, settings.llm),
                "aktiv": aktiv,
            }
        )
    return leute
