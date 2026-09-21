"""Was die Modelle unterscheidet - und was sie kosten.

Die Preistabelle nebenan sagt, was ein Token kostet. Das genügt der
Kasse, aber nicht dem Betreiber: Wer im Dashboard eine Rolle umstellt,
sieht dort neun Namen und keinen Anhaltspunkt, was die Wahl bedeutet.
"Opus 5" sagt nichts darüber, ob es das Dreifache oder das Zehnfache
kostet und ob es an dieser Stelle überhaupt etwas bringt.

Deshalb hier zu jedem Modell ein Satz, wofür es taugt, ein Satz, was es
ausmacht - und eine Zahl, die man vergleichen kann. Der Faktor ist
ehrlicher als der Tokenpreis: Ob Ausgabe fünfmal so teuer ist wie
Eingabe, hilft niemandem beim Abwägen; dass ein Aufruf fünfmal so viel
kostet wie der billigste, schon.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pricing import PRICING, ModelPrice

# Wie sich ein Aufruf in diesem Betrieb zusammensetzt. Die Rollen
# arbeiten eingabelastig: Prompt, Steckbrief, Suchergebnisse und die
# eigene Vorgeschichte sind ein Vielfaches dessen, was am Ende als
# Entwurf herauskommt. Mit diesem Verhältnis lässt sich aus zwei Preisen
# eine Zahl machen, die man vergleichen kann.
ANTEIL_EINGABE = 0.8
ANTEIL_AUSGABE = 0.2


@dataclass(frozen=True, slots=True)
class Steckbrief:
    """Wofür ein Modell taugt, in der Sprache dieses Betriebs."""

    anzeige: str
    eignung: str
    """Wofür man es hier nimmt - eine Rolle, kein Werbeversprechen."""

    merkmal: str
    """Was es ausmacht, gegenüber den anderen in der Liste."""

    websuche: bool
    """Ob es die neuere Websuche kann. Für die Prüfung entscheidend."""


STECKBRIEFE: dict[str, Steckbrief] = {
    "claude-fable-5-1": Steckbrief(
        "Fable 5.1",
        "Nur, wenn ein Beitrag wirklich schwierig ist.",
        "Das stärkste Modell - und mit Abstand das teuerste. Für den "
        "täglichen Betrieb ist es Verschwendung.",
        True,
    ),
    "claude-fable-5": Steckbrief(
        "Fable 5",
        "Wie Fable 5.1, eine Fassung älter.",
        "Gleicher Preis wie 5.1 ohne dessen Verbesserungen - es gibt "
        "keinen Grund, es der neueren Fassung vorzuziehen.",
        True,
    ),
    "claude-opus-5": Steckbrief(
        "Opus 5",
        "Für den Chef und die Endprüfung: entscheiden und widersprechen.",
        "Merkt, wenn etwas nicht zusammenpasst, und sagt es. Genau das "
        "will man bei einer Prüfung, die etwas verwerfen soll.",
        True,
    ),
    "claude-opus-4-8": Steckbrief(
        "Opus 4.8",
        "Wie Opus 5, eine Fassung älter.",
        "Gleicher Preis wie Opus 5. Nur nehmen, wenn ein Beitrag mit "
        "Opus 5 auffällig schlechter wurde.",
        True,
    ),
    "claude-opus-4-7": Steckbrief(
        "Opus 4.7",
        "Ältere Opus-Fassung.",
        "Gleicher Preis, ältere Ergebnisse. Kein Grund für die Wahl.",
        True,
    ),
    "claude-opus-4-6": Steckbrief(
        "Opus 4.6",
        "Ältere Opus-Fassung.",
        "Gleicher Preis, ältere Ergebnisse. Kein Grund für die Wahl.",
        True,
    ),
    "claude-sonnet-5": Steckbrief(
        "Sonnet 5",
        "Das Arbeitspferd: Stoffsuche, Texte, Bildsprache.",
        "Kann alles, was der Betrieb braucht, zum halben Opus-Preis. "
        "Wenn du nicht weisst, was du nehmen sollst: das hier.",
        True,
    ),
    "claude-sonnet-4-6": Steckbrief(
        "Sonnet 4.6",
        "Ältere Sonnet-Fassung.",
        "Teurer als Sonnet 5 und nicht besser. Steht nur in der Liste, "
        "weil es die Schnittstelle noch kennt.",
        True,
    ),
    "claude-haiku-4-5": Steckbrief(
        "Haiku 4.5",
        "Nur für Handgriffe: kürzen, umbenennen, sortieren.",
        "Schnell und sehr günstig - aber für alles, was ein Urteil "
        "verlangt, merklich schwächer.",
        False,
    ),
}


def mischpreis(preis: ModelPrice) -> float:
    """Was eine Million Token kosten, im Verhältnis dieses Betriebs."""
    return (
        preis.input_per_mtok * ANTEIL_EINGABE + preis.output_per_mtok * ANTEIL_AUSGABE
    )


def _guenstigster() -> float:
    return min(mischpreis(p) for p in PRICING.values())


def faktor(modell: str) -> float:
    """Wievielmal so teuer wie das billigste Modell in der Liste.

    Die Zahl, auf die es beim Vergleichen ankommt. Ein Faktor rechnet
    sich im Kopf, zwei Tokenpreise nicht.
    """
    preis = PRICING.get(modell)
    if preis is None:
        return 0.0
    return mischpreis(preis) / _guenstigster()


def uebersicht() -> list[dict]:
    """Alle wählbaren Modelle mit Preis, Faktor und Steckbrief.

    Sortiert vom billigsten zum teuersten - so, wie man vergleicht, und
    nicht alphabetisch, wo Fable vor Haiku vor Opus steht und die
    Reihenfolge nichts bedeutet.
    """
    zeilen = []
    for modell, preis in PRICING.items():
        brief = STECKBRIEFE.get(modell)
        zeilen.append(
            {
                "id": modell,
                "anzeige": brief.anzeige if brief else modell,
                "eingabe": preis.input_per_mtok,
                "ausgabe": preis.output_per_mtok,
                "faktor": round(faktor(modell), 1),
                "eignung": brief.eignung if brief else "",
                "merkmal": brief.merkmal if brief else "",
                "websuche": brief.websuche if brief else True,
            }
        )
    return sorted(zeilen, key=lambda z: z["faktor"])
