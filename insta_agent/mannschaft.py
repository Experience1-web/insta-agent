"""Wer hier arbeitet - und womit.

Der Betrieb besteht nicht aus einem Agenten, sondern aus drei Rollen mit
verschiedenen Aufträgen: Einer schreibt, einer sieht auf die Gestaltung,
einer prüft. Diese Trennung ist der ganze Sinn der Sache - wer schreibt,
prüft nicht, und wer prüft, gestaltet nicht.

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
)

# Wo die Modellwahl des Betreibers liegt.
KEY_MODELLWAHL = "modellwahl"


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

ROLLEN: tuple[Rolle, ...] = (CHEF, BILDSPRACHE, ENDPRUEFUNG)
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


def aufstellung(identitaet, settings, wahl: dict | None = None) -> list[dict]:
    """Die Mannschaft, wie das Dashboard sie zeigt.

    Ohne Identität fehlt der Chef - dann steht der Betrieb noch nicht, und
    die übrigen Rollen warten.
    """
    leute: list[dict] = []
    for rolle in ROLLEN:
        if rolle.schluessel == "chef":
            if identitaet is None:
                continue
            name = identitaet.agent_name
            aufgabe = identitaet.motto
        else:
            name, aufgabe = rolle.name, rolle.aufgabe

        aktiv = True
        if rolle.abschaltbar:
            aktiv = bool(getattr(settings.posting, rolle.abschaltbar, True))

        leute.append(
            {
                "schluessel": rolle.schluessel,
                "name": name,
                "rolle": rolle.rolle,
                "aufgabe": aufgabe,
                "eigenschaften": list(rolle.eigenschaften),
                "rang": rolle.rang,
                "modell": modell_fuer(rolle.schluessel, wahl, settings.llm),
                "standard": standardmodell(rolle, settings.llm),
                "aktiv": aktiv,
            }
        )
    return leute
