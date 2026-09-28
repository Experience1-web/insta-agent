"""Der Sparmodus: ein Beitrag zum kleinsten Preis, der die Kriterien noch hält.

Ein Beitrag besteht aus Arbeit, die ihn trägt, und aus Arbeit, die ihn
besser macht. Tragend sind: ein echter Fund mit Quellen, eine
Endprüfung, die im Netz nachsieht, eine Nachbesserung, wenn sie etwas
findet, und ein Foto, das die Sache zeigt. Das bleibt im Sparmodus.

Gespart wird an allem anderen, in dieser Reihenfolge der Wirkung:

1. Das Modell. Wer auf Opus 5 schreibt, schreibt im Sparmodus auf
   Sonnet 5 - dasselbe Handwerk zu zwei Fünfteln des Preises. Die Stufe
   geht von "high" auf "medium": weniger Nachdenken, das bezahlt wird.
2. Die Websuche. Jede Suche kostet einen Cent und bringt Tausende Token
   an Treffern mit. Zwei statt vier Suchen je Auftrag halbieren den
   teuersten Teil von Stoffsuche und Prüfung.
3. Die zweite Stoffsuche wegen des Fotos. Nachgesetzt wird nur noch,
   wenn der Fund zu schwach ist - ohne freies Foto nimmt er ein
   Archivbild oder die Schriftfassung.
4. Die Bildsprache. Sie verbessert den Auftrag fürs Malen. Gemalt wird
   im Sparmodus nur, wenn es nichts kostet, und dann ohne ihren Rat.
5. Die Nebenarbeiten des Zyklus: Marktrecherche, Reflexion, Vorbilder,
   Kursprüfung und Geschäftsplanung. Sie ruhen; es gilt der letzte Stand.

Was der Betreiber für eine Rolle gewählt hat, wird dabei nie teurer:
Wer eine Rolle schon auf ein günstigeres Modell gestellt hat, behält es.

Der Sparmodus ist nicht der Notbetrieb. Der springt von selbst an, wenn
die Kasse fast leer ist, und arbeitet dann mit Haiku und ganz ohne
Websuche - das hält kein Kriterium mehr. Der Sparmodus ist eine Wahl.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .modelle import STECKBRIEFE, mischpreis
from .pricing import WEBSUCHE_USD, price_for

# Wo der Schalter liegt.
KEY_SPARMODUS = "sparmodus"

SPAR_MODELL = "claude-sonnet-5"
SPAR_SUCHEN = 2
SPAR_AUFWAND = "medium"

AUFWANDSTUFEN = ("low", "medium", "high", "xhigh", "max")

# Wie viele Ausgabe-Token eine Aufwandsstufe im Verhältnis zu "high"
# verbraucht. Anthropics eigene Messungen: "medium" erreicht bei
# Recherche und Wissensarbeit dieselbe Güte zu 70 bis 85 Prozent der
# Kosten; das Nachdenken ist der Teil, der wegfällt.
AUSGABE_JE_STUFE = {"low": 0.55, "medium": 0.75, "high": 1.0, "xhigh": 1.3, "max": 1.6}

# Was eine Websuche an Treffern ins Modell bringt, in Eingabe-Token.
TREFFER_JE_SUCHE = 8_000


def _stufe(aufwand: str) -> int:
    return AUFWANDSTUFEN.index(aufwand) if aufwand in AUFWANDSTUFEN else 2


def niedriger(aufwand: str, grenze: str = SPAR_AUFWAND) -> str:
    """Die niedrigere von zwei Aufwandsstufen."""
    return aufwand if _stufe(aufwand) <= _stufe(grenze) else grenze


def guenstiger(modell: str | None, obergrenze: str = SPAR_MODELL) -> str:
    """Das günstigere von zwei Modellen, im Mischpreis dieses Betriebs.

    Ein unbekanntes Modell gilt als teuer - die Preisliste schätzt es so
    ein - und wird im Sparmodus ersetzt.
    """
    if not modell:
        return obergrenze
    if mischpreis(price_for(modell)) <= mischpreis(price_for(obergrenze)):
        return modell
    return obergrenze


def spar_config(llm):
    """Die Einstellungen fürs Modell, wie sie im Sparmodus gelten."""
    return replace(
        llm,
        model=guenstiger(llm.model),
        research_model=guenstiger(llm.research_model),
        effort=niedriger(llm.effort),
        research_effort=niedriger(llm.research_effort),
        max_web_searches=min(llm.max_web_searches, SPAR_SUCHEN),
    )


def anzeige(modell: str) -> str:
    brief = STECKBRIEFE.get(modell)
    return brief.anzeige if brief else modell


# --------------------------------------------------------------------------
# Was ein Beitrag kostet - geschätzt
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Schritt:
    """Ein Modellaufruf im Lauf eines Zyklus, mit seiner üblichen Größe."""

    name: str
    rolle: str
    """Wessen Modell: stoff, chef, pruefung, bildsprache - oder leitung,
    recherche, routine für die Voreinstellungen ohne eigene Rolle."""

    eingabe: int
    """Eingabe-Token ohne Suchtreffer: Auftrag, Steckbrief, Fund, Entwurf."""

    ausgabe: int
    """Ausgabe-Token samt Nachdenken, bei der üblichen Stufe dieser Aufgabe."""

    recherche: bool
    """Ob die Aufgabe als Recherche läuft - dann gilt deren Aufwandsstufe."""

    suche: bool
    anteil: float
    """Wie oft je Beitrag. Nachsetzen und Nachbessern gibt es nicht immer."""

    spar_anteil: float
    schalter: str = ""
    """Die Einstellung, mit der sich der Schritt abschalten lässt."""


# Die Größen sind Erfahrungswerte aus den Aufträgen dieses Betriebs, keine
# Messung. Sie bestimmen vor allem das Verhältnis zwischen Normalbetrieb
# und Sparmodus; der Betrag selbst kommt aus den eigenen Zyklen, sobald
# es welche gibt.
JE_BEITRAG = (
    Schritt("Stoff suchen", "stoff", 7_000, 4_000, True, True, 1.35, 1.15, "stoff_noetig"),
    Schritt("Post schreiben", "chef", 9_000, 7_000, False, False, 1.0, 1.0),
    Schritt("Bildsprache", "bildsprache", 6_000, 2_500, True, True, 0.5, 0.0, "gestaltung_noetig"),
    Schritt("Endprüfung", "pruefung", 8_000, 4_000, True, True, 1.0, 1.0, "pruefung_noetig"),
    Schritt("Beitrag nachbessern", "chef", 10_000, 6_000, False, False, 0.6, 0.6, "pruefung_noetig"),
    Schritt("Nachprüfung", "pruefung", 8_000, 2_500, True, False, 0.6, 0.6, "pruefung_noetig"),
    Schritt("Bild angesehen", "routine", 700, 40, False, False, 14.0, 12.0),
)

# Nebenarbeiten, auf einen Zyklus umgelegt: Die Strategie alle sieben
# Zyklen, die Vorbilder alle vierzehn und so weiter.
JE_ZYKLUS = (
    Schritt("Strategie festlegen", "leitung", 6_000, 5_000, False, False, 1 / 7, 0.0),
    Schritt("Reflexion", "leitung", 6_000, 4_000, False, False, 0.25, 0.0),
    Schritt("Marktrecherche", "recherche", 6_000, 4_000, True, True, 1 / 7, 0.0),
    Schritt("Recherche ordnen", "routine", 5_000, 2_000, False, False, 1 / 7, 0.0),
    Schritt("Vorbilder ansehen", "recherche", 6_000, 4_000, True, True, 1 / 14, 0.0),
    Schritt("Vorbilder ordnen", "routine", 5_000, 2_000, False, False, 1 / 14, 0.0),
    Schritt("Lohnt sich das noch", "leitung", 5_000, 3_000, False, False, 1 / 5, 0.0),
    Schritt("Geschäftsmodell", "leitung", 5_000, 4_000, False, False, 1 / 14, 0.0),
)

# Gemalte Bilder je Beitrag, wenn es kein Foto gibt: das erste Bild in
# etwa jedem zweiten Beitrag, dazu ein, zwei Karten.
GEMALT_JE_BEITRAG = 2.0


def modell_der_rolle(rolle: str, settings, wahl: dict | None) -> str:
    """Das Modell, mit dem ein Schritt im Normalbetrieb läuft."""
    from ..mannschaft import modell_fuer

    llm = settings.llm
    if rolle == "leitung":
        return llm.model
    if rolle == "recherche":
        return llm.research_model
    if rolle == "routine":
        return llm.cheap_model
    return modell_fuer(rolle, wahl, llm)


def _kosten(modell: str, eingabe: int, ausgabe: float, suchen: int) -> float:
    preis = price_for(modell)
    return (
        eingabe * preis.input_per_mtok + ausgabe * preis.output_per_mtok
    ) / 1_000_000 + suchen * WEBSUCHE_USD


def _schritt_kosten(schritt: Schritt, settings, wahl: dict | None, *, spar: bool) -> float:
    if schritt.schalter and not getattr(settings.posting, schritt.schalter, True):
        return 0.0
    anteil = schritt.spar_anteil if spar else schritt.anteil
    if schritt.name in ("Beitrag nachbessern", "Nachprüfung"):
        anteil *= min(max(int(settings.posting.nachbesserungen), 0), 1)
    if anteil <= 0:
        return 0.0

    llm = settings.llm
    modell = modell_der_rolle(schritt.rolle, settings, wahl)
    stufe = llm.research_effort if schritt.recherche else llm.effort
    suchen = llm.max_web_searches if schritt.suche else 0
    ausgabe = float(schritt.ausgabe)
    if spar:
        if schritt.rolle != "routine":
            modell = guenstiger(modell)
            neue_stufe = niedriger(stufe)
            ausgabe *= AUSGABE_JE_STUFE[neue_stufe] / AUSGABE_JE_STUFE.get(stufe, 1.0)
        suchen = min(suchen, SPAR_SUCHEN)
    eingabe = schritt.eingabe + suchen * TREFFER_JE_SUCHE
    return anteil * _kosten(modell, eingabe, ausgabe, suchen)


def _bildkosten(settings, *, spar: bool) -> float:
    preis = float(settings.bild.kosten_pro_bild_usd or 0.0)
    if not settings.bild.aktiv or preis <= 0 or spar:
        return 0.0
    return GEMALT_JE_BEITRAG * preis


def beispielrechnung(settings, wahl: dict | None = None, *, spar: bool) -> float:
    """Was ein Zyklus mit einem Beitrag nach den Erfahrungswerten kostet, in USD."""
    beitraege = max(int(settings.posting.posts_per_day), 1)
    je_beitrag = sum(_schritt_kosten(s, settings, wahl, spar=spar) for s in JE_BEITRAG)
    je_beitrag += _bildkosten(settings, spar=spar)
    nebenbei = sum(_schritt_kosten(s, settings, wahl, spar=spar) for s in JE_ZYKLUS)
    return je_beitrag + nebenbei / beitraege


@dataclass(slots=True)
class Schaetzung:
    normal_usd: float
    spar_usd: float
    normal_grundlage: str
    spar_grundlage: str

    @property
    def ersparnis(self) -> float:
        """Wie viel der Sparmodus spart, als Anteil (0 bis 1)."""
        if self.normal_usd <= 0:
            return 0.0
        return max(0.0, 1.0 - self.spar_usd / self.normal_usd)


# So viele eigene Zyklen fließen höchstens in den Schnitt - ältere
# stammen oft aus einem Stand, in dem noch anders gearbeitet wurde.
SCHNITT_AUS = 10


def _schnitt(zyklen: list[dict], *, spar: bool) -> tuple[float | None, int]:
    passende = [
        z["kosten"] / max(z["beitraege"], 1)
        for z in zyklen
        if z["spar"] == spar and z["beitraege"] > 0 and z["kosten"] > 0
    ][:SCHNITT_AUS]
    if not passende:
        return None, 0
    return sum(passende) / len(passende), len(passende)


def schaetze(settings, wahl: dict | None = None, zyklen: list[dict] | None = None) -> Schaetzung:
    """Was ein Beitrag kostet - im Normalbetrieb und im Sparmodus.

    `zyklen` sind die eigenen, neueste zuerst: je Zyklus die Kosten, die
    Zahl der Beiträge und ob er im Sparmodus lief. Wo es davon genug gibt,
    zählen sie; die Erfahrungswerte liefern dann nur noch das Verhältnis.
    Eine Schätzung aus Preisen schlägt keine Zahl aus der eigenen Kasse.
    """
    normal_rechnung = beispielrechnung(settings, wahl, spar=False)
    spar_rechnung = beispielrechnung(settings, wahl, spar=True)

    normal_echt, normal_n = _schnitt(zyklen or [], spar=False)
    spar_echt, spar_n = _schnitt(zyklen or [], spar=True)

    # Ein einzelner normaler Zyklus ist oft der erste - mit allem, was
    # nur einmal anfällt. Erst ab zweien ist es ein Schnitt.
    normal_eigen = normal_echt is not None and normal_n >= 2

    # Eine eigene Zahl wird nie gegen eine Beispielrechnung gestellt -
    # das ergäbe eine Ersparnis, die es nicht gibt. Fehlt die eine Seite,
    # wird sie aus der anderen hochgerechnet, im Verhältnis der Rechnung.
    if normal_eigen:
        normal = normal_echt
        normal_grundlage = f"Schnitt deiner letzten {normal_n} Zyklen"
    elif spar_echt is not None and spar_rechnung > 0:
        normal = spar_echt * normal_rechnung / spar_rechnung
        normal_grundlage = "hochgerechnet aus deinen Sparbeiträgen"
    else:
        normal = normal_rechnung
        normal_grundlage = "Beispielrechnung"

    if spar_echt is not None:
        spar = spar_echt
        spar_grundlage = (
            "dein Sparbeitrag" if spar_n == 1 else f"Schnitt deiner letzten {spar_n} Sparbeiträge"
        )
    elif normal_eigen and normal_rechnung > 0:
        spar = normal * spar_rechnung / normal_rechnung
        spar_grundlage = "geschätzt aus deinen Zyklen"
    else:
        spar = spar_rechnung
        spar_grundlage = "Beispielrechnung"

    return Schaetzung(
        normal_usd=round(normal, 4),
        spar_usd=round(spar, 4),
        normal_grundlage=normal_grundlage,
        spar_grundlage=spar_grundlage,
    )


# --------------------------------------------------------------------------
# Was sich ändert - in Sätzen fürs Dashboard
# --------------------------------------------------------------------------


def _aufzaehlung(teile: list[str]) -> str:
    return teile[0] if len(teile) == 1 else ", ".join(teile[:-1]) + " und " + teile[-1]


def so_spart_er(settings, wahl: dict | None = None) -> list[str]:
    """Was der Sparmodus anders macht, ausgehend von der jetzigen Einstellung.

    Genau für diese Einstellung: Wer nur den Chef auf Opus hat, liest
    "Schreiben mit Sonnet 5 statt Opus 5" - nicht, dass auch Suchen und
    Prüfen billiger würden, wenn sie es gar nicht werden.
    """
    llm = settings.llm
    taetigkeit = {"chef": "Schreiben", "stoff": "Suchen", "pruefung": "Prüfen"}
    wechsel: dict[str, list[str]] = {}
    for rolle, name in taetigkeit.items():
        modell = modell_der_rolle(rolle, settings, wahl)
        if guenstiger(modell) != modell:
            wechsel.setdefault(modell, []).append(name)
    weniger_denken = any(
        _stufe(stufe) > _stufe(SPAR_AUFWAND) for stufe in (llm.effort, llm.research_effort)
    )

    zeilen: list[str] = []
    if wechsel:
        satz = "; ".join(
            f"{_aufzaehlung(wer)} mit {anzeige(SPAR_MODELL)} statt {anzeige(modell)}"
            for modell, wer in wechsel.items()
        )
        zeilen.append(satz + (" – und mit weniger Nachdenken." if weniger_denken else "."))
    elif weniger_denken:
        zeilen.append("Die Modelle bleiben, sie sind schon günstig – nur mit weniger Nachdenken.")
    else:
        zeilen.append("Die Modelle bleiben, sie sind schon günstig.")
    if llm.max_web_searches > SPAR_SUCHEN:
        zeilen.append(
            f"Höchstens {SPAR_SUCHEN} statt {llm.max_web_searches} Websuchen je Stoffsuche "
            "und Prüfung."
        )
    zeilen.append(
        "Nachgesetzt wird nur, wenn der Fund zu schwach ist – nicht, weil ein Foto fehlt."
    )
    if settings.bild.aktiv and settings.bild.kosten_pro_bild_usd > 0:
        zeilen.append("Keine Bildsprache-Runde und keine bezahlten gemalten Bilder.")
    else:
        zeilen.append("Keine Bildsprache-Runde vor dem Malen.")
    zeilen.append(
        "Marktrecherche, Reflexion, Vorbilder, Kursprüfung und Geschäftsplanung ruhen – "
        "es gilt der letzte Stand."
    )
    return zeilen


DAS_BLEIBT = (
    "Ein echter Fund mit Quellen aus der Websuche",
    "Die Endprüfung sieht im Netz nach – und bessert einmal nach, wenn sie etwas findet",
    "Jedes Foto wird angesehen, bevor es genommen wird",
    "Karussell, Reel und alle Knöpfe wie gewohnt",
)


__all__ = [
    "DAS_BLEIBT",
    "KEY_SPARMODUS",
    "SPAR_AUFWAND",
    "SPAR_MODELL",
    "SPAR_SUCHEN",
    "Schaetzung",
    "anzeige",
    "beispielrechnung",
    "guenstiger",
    "niedriger",
    "schaetze",
    "so_spart_er",
    "spar_config",
]
