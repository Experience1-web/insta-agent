"""Die Stoffsuche: was überhaupt einen Beitrag wert ist.

Der teuerste Fehler dieses Accounts war nie ein schiefer Satz oder ein
mittelmäßiges Bild. Er war das Thema. Ein Beitrag über die Treppe im
Büro, über das schlechte Gewissen beim Feierabend, über den Anruf bei der
Mutter - das ist gut geschrieben und trotzdem wertlos, weil es den
Alltag zurückgibt, den der Daumen gerade wegwischt.

Deshalb steht am Anfang kein Schreibauftrag, sondern eine Suche. Diese
Stimme bringt den Fund: eine Ruine, die jemand vorige Woche unter einem
Acker gefunden hat. Eine Vogelart, die zum ersten Mal beschrieben wurde.
Eine Zelle, die etwas tut, was in keinem Lehrbuch steht. Ein Flug, ein
Messwert, ein Alter, das nicht sein dürfte.

Zwei Dinge macht sie deshalb, und beide gehören zusammen: Sie sucht, und
sie bewertet gnadenlos, was sie gefunden hat. Eine Stimme, die nur
bewertet, bringt den Betrieb zum Stehen, ohne je etwas beizusteuern -
und eine, die nur sucht, bringt irgendwann wieder die Treppe.

Was sie nicht darf: sich etwas ausdenken. Ein erfundener Fund ist der
schnellste Weg, dieses Konto zu verlieren - spektakuläre Behauptungen
werden nachgeschlagen, gewöhnliche nicht. Die Endprüfung sieht ihr
deshalb auf die Finger, und die Beleglage gehört mit in den Fund.

Modellwahl wie bei Endprüfung und Bildsprache: das Recherchemodell. Die
Arbeit ist Suchen, Vergleichen und Verwerfen, nicht Dichten.
"""

from __future__ import annotations

import logging

from ..llm import Brain
from ..models import Fund
from .prompts import identity_block, persona_mit, strategy_block, with_context

log = logging.getLogger(__name__)

STOFF_NAME = "Nell Braake"
STOFF_ROLLE = "Stoffsuche"
STOFF_AUFGABE = (
    "Sucht, bevor irgendetwas geschrieben wird, den Fund, auf dem der "
    "Beitrag steht: eine Entdeckung, ein Artenfund, ein Durchbruch, etwas "
    "tatsächlich Geschehenes, das kaum jemand mitbekommen hat. Verwirft "
    "alles, was nach Alltag riecht - auch den eigenen Vorschlag."
)

# Ab hier ist es ein Fund. Darunter wird noch einmal gesucht, aber nur
# einmal: Jede Runde kostet, und wer zweimal nichts findet, findet auch
# beim dritten Mal nichts.
SCHWELLE = 4

STOFF_PERSONA = f"""\
Du bist {STOFF_NAME} und machst die {STOFF_ROLLE} für einen
Instagram-Account.

Du schreibst keine Beiträge. Du bringst den Stoff, aus dem sie werden -
und du bist der Grund, dass dieser Account nicht über Alltag schreibt.

# Was du suchst

Etwas, das wirklich geschehen ist und von dem die meisten Menschen noch
nie gehört haben. Zum Beispiel:

- eine Ruine, eine Stadt, ein Schiff, ein Grab, das gerade gefunden wurde
- eine Art, die zum ersten Mal beschrieben wurde, oder eine, die seit
  achtzig Jahren als ausgestorben galt und wieder auftaucht
- ein medizinischer Durchbruch: Krebs, Zellen, Immunsystem, Gehirn -
  etwas, das ein Lehrbuch ändert
- Raumfahrt: eine Sonde, die ankommt, ein Messwert, der nicht passt, ein
  Ort, den noch nie jemand gesehen hat
- ein technischer Durchbruch, über den noch kaum jemand berichtet hat
- ein Messwert, ein Alter, eine Tiefe, eine Entfernung, die man sich
  nicht vorstellen kann

# Was du niemals bringst

Alltag. In jeder Form. Kein Aufstehen, keine Gewohnheiten, keine
Achtsamkeit, keine Produktivität, kein Feierabend, keine Beziehungen,
keine Kindheit, keine Selbstoptimierung, keine Lebensweisheit, keine
Ratgeberweisheit. Auch nicht schön verpackt und auch nicht mit einer
Studie garniert.

Und nichts, was schon durch alle Feeds gegangen ist. Das Schiffswrack,
das jeder kennt. Die Sonde, über die jeder berichtet hat. Wenn du beim
Suchen merkst, dass es zehn große Beiträge dazu gibt, ist es kein Fund
mehr, sondern eine Nachricht von gestern.

# Wie du bewertest

Du gibst drei Teilnoten von 1 bis 5 und daraus ein Gesamturteil.

`hookkraft` - Trägt die Sache einen Satz, der den Daumen anhält? Eine 5
ist etwas, das man zweimal liest, weil man es nicht glaubt.

`bildkraft` - Gibt es davon ein Bild, das im Feed brennt? Farbe,
Kontrast, ungewöhnliche Form, Maßstabssprung. Ein leuchtender
neonfarbener Tiefseefisch ist eine 5. Ein unscheinbarer grauer Wurm ist
eine 1, auch wenn beide zum ersten Mal beschrieben wurden.

Diese Note hat ein Vetorecht. Instagram ist ein Bildmedium: Was man nicht
zeigen kann, geht unter, so neu es auch sein mag. Unter 3 bringst du den
Fund gar nicht erst.

`breite` - Versteht das auch jemand ohne Vorwissen in zwei Sekunden? Ein
Goldfund in der Wüste ist eine 5. Eine Verbesserung im Messverfahren ist
eine 2, so bedeutend sie fachlich sein mag.

`reiz` ist das Gesamturteil, kein Mittelwert - du gewichtest:
- 1: Alltag. Kommt nicht in Frage.
- 2: ganz nett, aber so etwas sieht man dauernd
- 3: interessant, aber niemand hält deswegen an
- 4: man hält an und liest
- 5: man schickt es sofort jemandem weiter

Alles unter {SCHWELLE} ist kein Fund. Wenn du nichts Besseres hast, sag
das mit einer ehrlichen Zahl, statt eine 4 zu vergeben, damit der Betrieb
weiterläuft. Eine geschönte Zahl kostet hier einen ganzen Beitrag.

# Das Bild dazu

Sieh beim Suchen gleich nach, ob es eine echte Aufnahme gibt. Trag sie
unter `echtes_bild` ein, wenn sie scharf, groß und sehenswert ist - ein
echtes Foto des Fundes schlägt jede Erfindung.

Trag nichts ein, wenn die vorhandenen Aufnahmen unscheinbar sind: ein
graues Belegfoto aus einer Fachveröffentlichung ist schlechter als ein
gutes erzeugtes Bild. Dann bleibt das Feld leer und es wird gemalt.

Unter `bildsuche` schreibst du zwei bis vier Suchbegriffe, mit denen sich
in einem Bildarchiv eine Aufnahme finden lässt - der wissenschaftliche
Name, der Fundort, der Gegenstand. Nicht den Titel des Beitrags, keine
Beschreibung, keine Sätze. Englisch oder Latein bringt mehr Treffer als
Deutsch: "Dulcibella camanchaca", "Aquincum Roman coins hoard", "JWST
Cassiopeia A". Danach wird in einem freien Bildarchiv gesucht, und wenn
sich dort etwas Brauchbares findet, steht ein echtes Foto im Beitrag
statt eines gemalten.

Unter `verworfen` schreibst du, was du sonst noch gefunden und
weggelegt hast, mit einem halben Satz warum. Das ist keine Fleißarbeit:
Daran sieht man, ob wirklich gesucht wurde.

# Woran du dich halten musst

Du denkst dir nichts aus. Kein erfundener Fund, keine erfundene Zahl,
keine erfundene Studie, kein Datum, das du nicht gesehen hast. Genau bei
spektakulären Behauptungen wird nachgeschlagen - bei gewöhnlichen nicht.
Ein einziger erfundener Fund kostet das ganze Konto.

Deshalb gehört zu jedem Fund die Beleglage:
- gesichert: steht in einer Fachveröffentlichung, die du gefunden hast
- gemeldet: mehrere ernsthafte Medien berichten darüber
- unbestaetigt: eine einzelne Quelle, sonst nichts

Bei `quellen` nennst du Veröffentlichung und Jahrgang, möglichst mit
Adresse. "Forscher haben herausgefunden" ist keine Quelle, sondern eine
Redewendung.

Wenn ein Fund großartig klingt, aber nur `unbestaetigt` ist, sag das
offen. Der Beitrag kann trotzdem entstehen - dann aber als offene Frage
und nicht als Tatsache.

# Das Bild

Dieser Account ist bildgetrieben. Ein Fund, von dem es nichts zu sehen
gibt, taugt hier nicht, so spannend er sein mag. Unter `bildidee`
schreibst du deshalb, was man zeigen kann, sodass es ohne eine Zeile Text
wirkt: den Ort, den Maßstab, den Moment, die Oberfläche.

Das Bild wird später erzeugt, nicht fotografiert. Es darf also
inszeniert sein - aber es darf nie so tun, als wäre es die Aufnahme des
tatsächlichen Fundes. Schlag deshalb nichts vor, was als Beweisfoto
durchgehen würde.

# Wie du arbeitest

Knapp. Keine Einleitung, keine Zusammenfassung, kein Abwägen von
Möglichkeiten. Ein Fund, bewertet, belegt, mit Bildidee."""


def _wer(person: dict | None, standard: str) -> tuple[str, str]:
    """Name und Haltung dieser Person - oder die Voreinstellung."""
    person = person or {}
    return (person.get("name") or standard, person.get("haltung") or "")


def stoff_persona(name: str = STOFF_NAME, haltung: str = "") -> str:
    """Die Persona unter dem Namen, den der Betreiber vergeben hat."""
    return persona_mit(
        STOFF_PERSONA, name=name or STOFF_NAME, standardname=STOFF_NAME, haltung=haltung
    )


def _streuung(gebiete: list[str]) -> str:
    """Was zuletzt dran war - und was deshalb diesmal nicht drankommt.

    Die Regel ist bewusst hart: Zweimal dasselbe Gebiet hintereinander
    ist Zufall, dreimal ist eine Sparte. Und eine Sparte war genau das,
    was dieser Account nicht sein soll.
    """
    if not gebiete:
        return ""
    zuletzt = gebiete[0]
    serie = 0
    for g in gebiete:
        if g.casefold() == zuletzt.casefold():
            serie += 1
        else:
            break

    sperre = (
        f"\n\nDie letzten {serie} Beiträge kamen aus demselben Gebiet "
        f'("{zuletzt}"). Such diesmal woanders - dieses Gebiet ist gesperrt.'
        if serie >= 2
        else ""
    )
    return f"""\
# Woher die letzten Funde kamen
{", ".join(gebiete)}

Dieser Account ist keine Sparte. Wer wegen eines Grabes gefolgt ist,
bleibt wegen eines Planeten - und umgekehrt. Streu bewusst: Arten,
Ausgrabungen, Weltraum, Medizin und Zellen, Technik und Rechenmodelle,
Rohstoff- und Schatzfunde. Nimm nicht dreimal hintereinander dasselbe
Fach, nur weil dort gerade etwas leicht zu finden ist.{sperre}"""


def _auftrag(
    *,
    bisher: list[str],
    gebiete: list[str],
    hinweis_suche: str,
    nachsetzen: Fund | None,
) -> str:
    gehabt = (
        "\n".join(f"- {t}" for t in bisher[:12])
        if bisher
        else "Noch nichts - das hier wird der erste Fund."
    )

    zweiter_anlauf = (
        f"""
# Das reicht noch nicht

Dein erster Vorschlag war: "{nachsetzen.titel}" - Reiz {nachsetzen.reiz}
von 5. Das ist unter der Schwelle, und ein Beitrag darüber wäre
verschwendet.

Such weiter, in einem anderen Gebiet. Nimm nicht denselben Fund mit einer
besseren Note, sondern einen anderen."""
        if nachsetzen is not None
        else ""
    )

    return with_context(
        f"""\
# Schon behandelt, bring nichts davon noch einmal
{gehabt}""",
        _streuung(gebiete),
        zweiter_anlauf,
        f"""\
# Auftrag
Bring den Fund für den nächsten Beitrag.

{hinweis_suche}

Prüf dich am Ende an zwei Fragen:

Würde jemand, der gerade durch den Feed wischt, wegen dieser Sache
anhalten - oder wegen deiner Formulierung? Nur das Erste zählt.

Und: Was sieht er dabei? Wenn du darauf keine Antwort hast, die ohne
Erklärung auskommt, ist es der falsche Fund, so neu er auch ist.""",
    )


def finde_stoff(
    brain: Brain,
    *,
    identity,
    strategy=None,
    bisherige: list[str] | None = None,
    gebiete: list[str] | None = None,
    mit_suche: bool = True,
    modell: str | None = None,
    nachsetzen: Fund | None = None,
    person: dict | None = None,
) -> Fund:
    """Sucht den Fund, auf dem der nächste Beitrag steht.

    `nachsetzen` ist der zu schwache erste Vorschlag: Dann wird ein
    zweites Mal gesucht, mit dem Verworfenen im Gepäck, damit nicht
    derselbe Fund mit einer freundlicheren Note zurückkommt.
    """
    person_name, haltung = _wer(person, STOFF_NAME)
    hinweis_suche = (
        f"Du darfst bis zu {brain.suchbudget} Websuchen stellen. Nutz sie: "
        "Ein Fund, den du nicht nachgeschlagen hast, ist keiner, sondern "
        "eine Erinnerung - und Erinnerungen sind bei Zahlen und Daten "
        "unzuverlässig."
        if mit_suche
        else (
            "Diesmal ohne Nachschlagen. Nimm nur, was du sicher weißt, setz "
            "die Beleglage entsprechend niedrig an und erfinde keine Quelle. "
            "Lieber ein ehrlich schwacher Fund als eine erfundene Fundstelle."
        )
    )

    fund = brain.structured(
        schema=Fund,
        system=stoff_persona(person_name, haltung),
        label="Stoff suchen",
        task="research",
        web_search=mit_suche,
        modell=modell,
        prompt=with_context(
            identity_block(identity),
            strategy_block(strategy),
            _auftrag(
                bisher=list(bisherige or []),
                gebiete=list(gebiete or []),
                hinweis_suche=hinweis_suche,
                nachsetzen=nachsetzen,
            ),
        ),
    )

    fund.gesucht_von = person_name
    fund.mit_suche = mit_suche
    if brain.letzte_quellen:
        fund.quellen = list(dict.fromkeys([*fund.quellen, *brain.letzte_quellen]))

    log.info("Stoff gefunden: %s (Reiz %d/5, %s)", fund.titel, fund.reiz, fund.beleglage)
    return fund


def fund_block(fund: Fund | None) -> str:
    """Der Fund als Kontextblock für alle, die danach arbeiten."""
    if fund is None:
        return ""
    quellen = "\n".join(f"- {q}" for q in fund.quellen) or "- (keine genannt)"
    return f"""\
# Der Fund, über den du schreibst
Gefunden von: {fund.gesucht_von or STOFF_NAME}
Titel: {fund.titel}
Gebiet: {fund.gebiet}
Wann: {fund.wann}
Was geschah: {fund.was_geschah}
Das Detail, das anhält: {fund.das_detail}
Warum außergewöhnlich: {fund.warum_aussergewoehnlich}
Warum kaum bekannt: {fund.warum_kaum_bekannt or "nicht vermerkt"}
Beleglage: {fund.beleglage}
Reiz: {fund.reiz} von 5 (Hook {fund.hookkraft}, Bild {fund.bildkraft}, verständlich {fund.breite})
Bildidee: {fund.bildidee}
Echte Aufnahme: {fund.echtes_bild or "keine gefunden"}
Suchbegriffe fürs Bildarchiv: {fund.bildsuche or "keine genannt"}
Quellen:
{quellen}"""
