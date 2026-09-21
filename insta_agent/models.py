"""Alle strukturierten Ausgaben, die der Agent vom Modell zurückbekommt.

Jedes Modell hier ist ein Vertrag: Claude füllt es über Structured Outputs,
der Rest des Programms arbeitet nur noch mit validierten Objekten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Identität - erfindet sich der Agent einmalig selbst
# --------------------------------------------------------------------------


class Identity(BaseModel):
    """Wer der Agent ist und wer der Account ist.

    Zwei getrennte Dinge: Der Agent ist die Person, die den Account
    betreibt. Der Account ist die Marke, die sie aufbaut. Beides denkt er
    sich selbst aus.
    """

    agent_name: str = Field(
        description="Der Name, den du dir selbst gibst - als Person, nicht als Marke"
    )
    agent_why: str = Field(description="Warum du dich so nennst, in einem Satz")

    handle: str = Field(description="Vorgeschlagener Instagram-Handle, ohne @, max 30 Zeichen")
    display_name: str = Field(description="Angezeigter Profilname")
    motto: str = Field(description="Das selbst gewählte Motto, ein prägnanter Satz")
    niche: str = Field(description="Die inhaltliche Nische in einem Satz")
    target_audience: str = Field(description="Wen der Account erreichen will")
    tone_of_voice: str = Field(description="Sprachstil: Wortwahl, Ansprache, Haltung")
    visual_identity: str = Field(description="Bildsprache: Farben, Typografie, Bildaufbau")
    content_pillars: list[str] = Field(
        description="3 bis 5 wiederkehrende Themensäulen", min_length=3, max_length=5
    )
    bio: str = Field(description="Profiltext, max 150 Zeichen")
    why_this_works: str = Field(description="Begründung aus der Marktanalyse")


# --------------------------------------------------------------------------
# Marktanalyse
# --------------------------------------------------------------------------


class Competitor(BaseModel):
    handle_or_name: str
    what_they_do_well: str
    gap_we_can_exploit: str


class MarketAnalysis(BaseModel):
    """Ergebnis einer Rechercherunde."""

    summary: str = Field(description="Was gerade in der Nische passiert, 3 bis 5 Sätze")
    trends: list[str] = Field(description="Konkrete, aktuell laufende Trends")
    competitors: list[Competitor] = Field(default_factory=list)
    content_opportunities: list[str] = Field(description="Ungenutzte Formate oder Themen")
    risks: list[str] = Field(default_factory=list, description="Sättigung, Plattformrisiken")
    confidence: Literal["low", "medium", "high"] = "medium"
    sources: list[str] = Field(default_factory=list, description="URLs der Webrecherche")


# --------------------------------------------------------------------------
# Strategie und Inhalte
# --------------------------------------------------------------------------


class StrategyUpdate(BaseModel):
    """Was der Agent nach einer Analyse an seinem Kurs ändert."""

    current_goal: str = Field(description="Das eine Ziel für die nächsten 7 Tage")
    reasoning: str = Field(description="Warum dieses Ziel, gestützt auf Zahlen und Recherche")
    changes: list[str] = Field(description="Konkrete Änderungen gegenüber vorher")
    posting_cadence: str = Field(description="Wie oft und wann gepostet wird")
    kpis_to_watch: list[str] = Field(description="Woran der Erfolg gemessen wird")
    experiments: list[str] = Field(
        default_factory=list, description="Was diese Woche bewusst getestet wird"
    )


# --------------------------------------------------------------------------
# Der Stoff - worüber überhaupt geschrieben wird
# --------------------------------------------------------------------------


class Fund(BaseModel):
    """Ein Fund: die außergewöhnliche Sache, auf der ein Beitrag steht.

    Die härteste Grenze dieses Accounts ist nicht der Text und nicht das
    Bild, sondern das Thema. Ein Beitrag über den Alltag ist nicht zu
    retten - egal wie gut geschrieben, egal wie schön fotografiert. Wer
    gerade wischt, hat den Alltag schon, er braucht ihn nicht als Beitrag.

    Deshalb steht am Anfang kein Schreibauftrag, sondern eine Suche: Was
    ist tatsächlich geschehen, das jemanden den Daumen anhalten lässt?
    """

    titel: str = Field(description="Der Fund in einer Zeile, sachlich, ohne Reißerei")
    gebiet: str = Field(
        description="Archäologie, Artenfund, Medizin, Zellbiologie, Raumfahrt, Technik ..."
    )
    was_geschah: str = Field(
        description="Was gefunden, entdeckt oder erreicht wurde, in zwei bis drei Sätzen"
    )
    das_detail: str = Field(
        description=(
            "Der eine Satz, bei dem jemand aufhört zu wischen. Eine Zahl, ein "
            "Maß, ein Alter, ein Widerspruch - etwas Konkretes, nichts Gefühltes."
        )
    )
    warum_aussergewoehnlich: str = Field(
        description="Warum das kein Alltag ist, sondern selten - in zwei Sätzen"
    )
    warum_kaum_bekannt: str = Field(
        default="",
        description="Warum das noch kaum jemand mitbekommen hat",
    )
    wann: str = Field(description="Wann es geschah oder veröffentlicht wurde")
    quellen: list[str] = Field(
        default_factory=list,
        description="Wo es steht: Veröffentlichung, Jahrgang, möglichst URL",
    )
    beleglage: Literal["gesichert", "gemeldet", "unbestaetigt"] = Field(
        default="gemeldet",
        description=(
            "gesichert: in einer Fachveröffentlichung nachzulesen. gemeldet: "
            "mehrere ernsthafte Medien berichten. unbestaetigt: eine einzelne "
            "Quelle, mehr nicht - damit geht kein Beitrag hinaus."
        ),
    )
    reiz: int = Field(
        ge=1,
        le=5,
        description=(
            "1: Alltag, das kennt jeder. 2: ganz nett, aber schon oft gesehen. "
            "3: interessant, aber nicht atemberaubend. 4: man hält an und liest. "
            "5: man schickt es sofort jemandem weiter."
        ),
    )
    hookkraft: int = Field(
        default=3,
        ge=1,
        le=5,
        description=(
            "Trägt die Sache einen Satz, der den Daumen anhält? 5 heißt: "
            "Man muss zweimal hinsehen, weil man es nicht glaubt."
        ),
    )
    bildkraft: int = Field(
        default=3,
        ge=1,
        le=5,
        description=(
            "Gibt es davon ein Bild, das im Feed brennt? Farbe, Kontrast, "
            "ungewöhnliche Form, Maßstab. Ein leuchtender Tiefseefisch ist "
            "eine 5, ein grauer Wurm eine 1 - auch wenn beide neu sind."
        ),
    )
    breite: int = Field(
        default=3,
        ge=1,
        le=5,
        description=(
            "Versteht das auch jemand ohne Vorwissen in zwei Sekunden? "
            "Ein Goldfund ist eine 5, eine Verbesserung im Messverfahren "
            "eine 2 - so spektakulär sie fachlich sein mag."
        ),
    )
    bildidee: str = Field(
        description="Was man von diesem Fund zeigen kann, sodass es ohne Text wirkt"
    )
    echtes_bild: str = Field(
        default="",
        description=(
            "Wo es eine echte Aufnahme gibt, die aussieht wie beschrieben - "
            "Adresse oder Quelle. Leer lassen, wenn du keine gefunden hast "
            "oder die vorhandenen unscheinbar sind."
        ),
    )
    bildsuche: str = Field(
        default="",
        description=(
            "Zwei bis vier Wörter, mit denen sich in einem Bildarchiv eine "
            "Aufnahme der Sache finden lässt: der wissenschaftliche Name, "
            "der Fundort, der Gegenstand. Nicht der Titel des Beitrags und "
            "keine Beschreibung - Suchbegriffe. Englisch oder Latein bringt "
            "mehr Treffer als Deutsch."
        ),
    )
    verworfen: list[str] = Field(
        default_factory=list,
        description="Was du auch gefunden und als zu gewöhnlich verworfen hast",
    )
    gesucht_von: str = Field(default="", description="Wer gesucht hat")
    mit_suche: bool = Field(default=True, description="Ob nachgeschlagen werden konnte")

    @property
    def taugt(self) -> bool:
        """Ab vier ist es ein Fund. Darunter ist es ein Thema.

        Die Bildkraft hat ein Veto: Instagram ist ein Bildmedium, und was
        man nicht zeigen kann, geht hier unter - so neu es auch ist.
        """
        return self.reiz >= 4 and self.bildkraft >= 3

    @property
    def belegt(self) -> bool:
        return self.beleglage in ("gesichert", "gemeldet")


class VisualSpec(BaseModel):
    """Bauplan für das Bild. Wird lokal mit Pillow gerendert, kostet nichts."""

    layout: Literal["quote", "stat", "list", "split", "title"] = "quote"
    headline: str = Field(description="Hauptzeile, kurz und schlagend")
    subline: str = Field(default="", description="Optionale zweite Zeile")
    body_lines: list[str] = Field(
        default_factory=list, description="Bis zu 5 Zeilen für Listen- oder Stat-Layout"
    )
    background_hex: str = Field(default="#111318", description="Hintergrundfarbe als #rrggbb")
    text_hex: str = Field(default="#F5F5F0", description="Textfarbe als #rrggbb")
    accent_hex: str = Field(default="#E4572E", description="Akzentfarbe als #rrggbb")
    akzentwort: str = Field(
        default="",
        description=(
            "Ein Wort oder eine Zahl aus der Headline, die farbig gesetzt "
            "wird. Das eine Wort, an dem die Sache hängt - meist die Zahl, "
            "die Tiefe oder der Name. Nicht mehr als zwei Wörter: Wenn alles "
            "hervorgehoben ist, ist nichts hervorgehoben."
        ),
    )
    footer: str = Field(default="", description="Kleiner Fußtext, meist der Handle")


class Karte(BaseModel):
    """Eine Seite eines Karussells: ein Bild, eine Tatsache.

    Der Grund, warum ein Beitrag mehrere Bilder bekommt, ist nicht die
    Menge, sondern die Bewegung: Wer wischt, bleibt. Jede Karte muss
    deshalb fuer sich stehen und trotzdem zur naechsten ziehen.

    Und sie muss eine Tatsache tragen, keine Fortsetzung eines Satzes.
    "59,35 Lichtjahre entfernt" ist eine Karte. "und ausserdem" ist
    keine.
    """

    text: str = Field(
        description=(
            "Was auf diesem Bild steht. Eine einzelne Tatsache, hoechstens "
            "acht Woerter, ohne Punkt am Ende. Konkret: eine Zahl, eine "
            "Entfernung, ein Jahr, ein Name - nicht 'faszinierend'."
        )
    )
    akzentwort: str = Field(
        default="",
        description=(
            "Das eine Wort oder die eine Zahl aus dem Text, die farbig "
            "gesetzt wird. Meist die Zahl."
        ),
    )
    bildwunsch: str = Field(
        default="",
        description=(
            "Englischer Prompt fuer das Bild dieser Karte, falls gemalt "
            "werden muss. Muss zum Bild der ersten Karte passen: dieselbe "
            "Lichtstimmung, dieselbe Farbwelt, derselbe Bildabstand. Eine "
            "Reihe, kein Sammelsurium."
        ),
    )
    bildsuche: str = Field(
        default="",
        description=(
            "Zwei bis vier Woerter fuer die Suche nach einer echten "
            "Aufnahme zu dieser Karte, auf Englisch. Leer lassen, wenn es "
            "davon kein Foto geben kann."
        ),
    )


class PostDraft(BaseModel):
    """Ein fertiger Post-Entwurf.

    Die Felder folgen der Reihenfolge, in der ein Zuschauer sie trifft:
    zuerst das Bild mit dem Text darauf, dann die erste Caption-Zeile, dann
    der Rest. Was in den ersten anderthalb Sekunden nicht zieht, wird nie
    gelesen - deshalb ist `hook_text_on_screen` ein eigenes Feld und nicht
    ein Nebenprodukt der Caption.
    """

    pillar: str = Field(description="Zu welcher Themensäule der Post gehört")

    # -- Der Hook: was auf dem Bild steht ---------------------------------
    hook_text_on_screen: str = Field(
        default="",
        description=(
            "Der Text auf dem Bild selbst. Höchstens 7 Wörter. Muss sofort "
            "Neugier, Erstaunen oder Widerspruch auslösen - ein Musterbruch."
        ),
    )
    image_generation_prompt: str = Field(
        default="",
        description=(
            "Englischer Prompt für Flux oder Midjourney: Bildinhalt, Licht, "
            "Stil, Format 9:16. Konkret genug, dass zweimal dasselbe Bild "
            "entsteht."
        ),
    )

    # -- Die Caption in ihren drei Teilen ---------------------------------
    hook: str = Field(description="Die erste Caption-Zeile, die zum Weiterlesen zwingt")
    caption: str = Field(description="Vollständige Caption inklusive Hook, max 2200 Zeichen")
    body_text: str = Field(
        default="",
        description="Der Haupttext mit Absätzen und Emojis, ohne die Hook-Zeile",
    )
    call_to_action: str = Field(description="Was der Leser tun soll")

    hashtags: list[str] = Field(description="Ohne #, gemischt aus groß, mittel und klein")

    first_comment_prompt: str = Field(
        default="",
        description=(
            "Eine offene Frage, die du selbst als ersten Kommentar setzt, "
            "damit die Diskussion beginnt. Nicht mit ja oder nein zu "
            "beantworten."
        ),
    )

    visual: VisualSpec

    karten: list[Karte] = Field(
        default_factory=list,
        description=(
            "Die weiteren Bilder zum Durchwischen, nach dem ersten. Zwei "
            "bis vier, wenn der Fund genug belegte Tatsachen hergibt - "
            "sonst weniger oder gar keine. Lieber ein starkes Bild als "
            "fuenf, von denen drei nichts sagen. Jede Karte eine Tatsache, "
            "keine Wiederholung dessen, was schon auf dem ersten Bild "
            "steht, und nichts Erfundenes, nur um auf eine Zahl zu kommen."
        ),
    )

    best_time_hint: str = Field(description="Wann dieser Post laufen sollte und warum")
    expected_outcome: str = Field(description="Was der Agent sich davon verspricht")

    @property
    def bildtext(self) -> str:
        """Was aufs Bild gehört - notfalls die Headline aus der Bildspezifikation.

        Ältere Entwürfe aus der Datenbank kennen `hook_text_on_screen` noch
        nicht. Sie sollen trotzdem ein Bild bekommen.
        """
        return self.hook_text_on_screen.strip() or self.visual.headline


# --------------------------------------------------------------------------
# Endpruefung - ein zweites Paar Augen vor der Freigabe
# --------------------------------------------------------------------------


class Befund(BaseModel):
    """Eine einzelne geprüfte Aussage aus dem Beitrag."""

    behauptung: str = Field(
        description="Die geprüfte Aussage, wörtlich aus dem Beitrag zitiert"
    )
    urteil: Literal["belegt", "ungenau", "falsch", "unbelegbar"] = Field(
        description=(
            "belegt: stimmt und ist auffindbar. ungenau: im Kern richtig, aber "
            "schief dargestellt. falsch: stimmt nicht. unbelegbar: keine Quelle "
            "zu finden - was für eine Zahl genauso schlimm ist wie falsch."
        )
    )
    begruendung: str = Field(description="Warum dieses Urteil, in ein bis zwei Sätzen")
    beleg: str = Field(default="", description="Fundstelle oder URL, falls vorhanden")


class Pruefbericht(BaseModel):
    """Das Urteil der Endprüfung über einen Beitrag.

    Der Agent zugespitzt formulieren zu lassen und ihn gleichzeitig selbst
    prüfen zu lassen, ist ein Interessenkonflikt: Wer den Satz geschrieben
    hat, will, dass er stehenbleibt. Deshalb prüft eine zweite Instanz mit
    eigenem Auftrag, die den Beitrag nicht geschrieben hat.
    """

    urteil: Literal["freigabe", "nachbessern", "ablehnen"] = Field(
        description=(
            "freigabe: alles belegt, kann raus. nachbessern: etwas ist schief, "
            "aber reparierbar. ablehnen: eine Zahl oder Quelle ist falsch oder "
            "erfunden - so darf das nicht erscheinen."
        )
    )
    zusammenfassung: str = Field(description="Das Urteil in zwei bis drei Sätzen")
    befunde: list[Befund] = Field(
        default_factory=list, description="Jede geprüfte Zahl, Quelle und Tatsachenbehauptung"
    )
    korrekturen: list[str] = Field(
        default_factory=list, description="Konkrete Änderungen, die den Beitrag retten würden"
    )
    quellen: list[str] = Field(default_factory=list, description="URLs, die nachgeschlagen wurden")
    geprueft_von: str = Field(default="", description="Wer geprüft hat")
    mit_suche: bool = Field(default=True, description="Ob nachgeschlagen werden konnte")

    @property
    def darf_raus(self) -> bool:
        return self.urteil == "freigabe"

    @property
    def beanstandet(self) -> list[Befund]:
        return [b for b in self.befunde if b.urteil != "belegt"]


# --------------------------------------------------------------------------
# Bildsprache - damit es nicht aussieht wie alles andere
# --------------------------------------------------------------------------


class NeueBildsprache(BaseModel):
    """Eine überarbeitete Bildsprache, ohne die übrige Identität anzufassen.

    Der Account bleibt derselbe - Nische, Motto, Tonfall, Themensäulen.
    Nur wie die Bilder aussehen, wird neu festgelegt. Sonst müsste man
    alles wegwerfen, um eine einzige Entscheidung zu ändern.
    """

    visual_identity: str = Field(
        description=(
            "Die neue Bildsprache, so geschrieben, dass ein Fotograf danach "
            "arbeiten könnte: Motivwelt, Lichtführung, Objektiv, Farbklima, "
            "Material, und wo Platz für Schrift bleibt"
        )
    )
    was_sich_aendert: str = Field(description="Was jetzt anders ist als vorher, in zwei Sätzen")
    beispielmotiv: str = Field(
        description="Ein konkretes Motiv aus der neuen Bildsprache, als Beispiel"
    )


class Gestaltungsurteil(BaseModel):
    """Was die Bildsprache über einen geplanten Beitrag sagt.

    Anders als die Endprüfung hält diese Stimme nichts auf. Gestaltung ist
    Geschmack, keine Wahrheit - ein Bild kann langweilig sein, ohne falsch
    zu sein. Was sie liefert, ist der bessere Vorschlag: einen überarbeiteten
    Bildprompt, der tatsächlich benutzt wird.
    """

    niveau: int = Field(
        ge=1, le=5, description="1 heißt beliebig, 5 heißt: das fällt im Feed auf"
    )
    urteil: str = Field(description="Das Gesamturteil in zwei bis drei Sätzen")
    staerken: list[str] = Field(default_factory=list, description="Was schon trägt")
    schwaechen: list[str] = Field(
        default_factory=list, description="Woran man es als Massenware erkennt"
    )
    verbesserungen: list[str] = Field(
        default_factory=list,
        description="Konkrete Eingriffe - nicht 'moderner', sondern was genau anders wird",
    )
    bildprompt: str = Field(
        default="",
        description=(
            "Der überarbeitete englische Bildprompt. Leer lassen, wenn der "
            "vorhandene nicht zu verbessern ist."
        ),
    )
    gesehen: list[str] = Field(
        default_factory=list,
        description="Was gerade läuft und woran man sich nicht anhängen sollte",
    )
    quellen: list[str] = Field(default_factory=list)
    geprueft_von: str = Field(default="")
    mit_suche: bool = Field(default=True)

    @property
    def taugt(self) -> bool:
        """Ab vier ist es gut genug, um so hinauszugehen."""
        return self.niveau >= 4


# --------------------------------------------------------------------------
# Reflexion - der Agent lernt aus seinen Zahlen
# --------------------------------------------------------------------------


class Reflection(BaseModel):
    what_worked: list[str]
    what_failed: list[str]
    hypotheses: list[str] = Field(description="Erklärungsversuche für die Zahlen")
    next_actions: list[str] = Field(description="Konkrete Schritte für den nächsten Zyklus")
    strategy_should_change: bool = Field(description="Ob eine neue Strategie nötig ist")


# --------------------------------------------------------------------------
# Ökonomie - der Agent soll sich selbst tragen
# --------------------------------------------------------------------------


class BusinessIdea(BaseModel):
    name: str
    pitch: str = Field(description="Ein Satz, der das Angebot erklärt")
    revenue_model: Literal[
        "digital_product", "affiliate", "sponsorship", "service", "subscription", "other"
    ]
    price_point_usd: float = Field(description="Realistischer Preis pro Einheit")
    required_followers: int = Field(description="Ab welcher Reichweite das realistisch wird")
    effort: Literal["low", "medium", "high"]
    first_step: str = Field(description="Der allererste konkrete Schritt")
    fits_identity_because: str
    monthly_revenue_estimate_usd: float = Field(description="Nüchterne Schätzung")


class MonetizationPlan(BaseModel):
    reasoning: str = Field(description="Wie der Agent zu dieser Reihenfolge kommt")
    ideas: list[BusinessIdea] = Field(min_length=1)
    recommended_now: str = Field(description="Name der Idee, die jetzt starten soll")
    what_the_operator_must_do: list[str] = Field(
        description="Schritte, die ein Mensch übernehmen muss, etwa Konten oder Auszahlungen"
    )


# --------------------------------------------------------------------------
# Gewinnorientierung: lohnt sich der Kurs noch?
# --------------------------------------------------------------------------


class Opportunity(BaseModel):
    """Eine Möglichkeit, mehr zu verdienen - nüchtern durchgerechnet."""

    name: str
    description: str = Field(description="Worum es geht, in zwei Sätzen")
    revenue_model: Literal[
        "digital_product", "affiliate", "sponsorship", "service", "subscription", "other"
    ]
    value_if_it_works_usd: float = Field(
        description="Umsatz in 90 Tagen, WENN es aufgeht. Nüchtern, nicht erhofft."
    )
    probability: float = Field(
        description="Wie wahrscheinlich es aufgeht, zwischen 0 und 1", ge=0.0, le=1.0
    )
    days_to_first_dollar: int = Field(description="Bis zum ersten verdienten Dollar")
    effort: Literal["low", "medium", "high"]
    needs_new_audience: bool = Field(
        description="Ob dafür eine andere Zielgruppe nötig wäre als die jetzige"
    )
    operator_must_do: list[str] = Field(
        default_factory=list, description="Was ein Mensch übernehmen muss"
    )
    why: str = Field(description="Warum diese Schätzung realistisch ist")

    @property
    def expected_value_usd(self) -> float:
        """Erwartungswert: was die Idee im Mittel einbringt.

        Eine Idee mit 10 Prozent Chance auf 1000 USD ist wenig wert -
        genau das macht diese Zahl sichtbar.
        """
        return self.value_if_it_works_usd * self.probability


class OpportunityAssessment(BaseModel):
    """Die regelmäßige Frage: weitermachen oder etwas anderes tun?"""

    current_path_value_usd: float = Field(
        description="Erwarteter Umsatz der nächsten 90 Tage, wenn alles bleibt wie es ist"
    )
    current_path_reasoning: str = Field(description="Wie diese Zahl zustande kommt")
    opportunities: list[Opportunity] = Field(default_factory=list)
    switching_cost: str = Field(
        description="Was ein Wechsel kostet: verlorene Follower, verlorene Zeit, verlorener Ruf"
    )
    recommendation: Literal["weitermachen", "ergaenzen", "wechseln"]
    reasoning: str = Field(description="Die Begründung, mit Zahlen")
    confidence: Literal["low", "medium", "high"]


# --------------------------------------------------------------------------
# Interne Zustandsobjekte, nicht vom Modell befüllt
# --------------------------------------------------------------------------


class CycleReport(BaseModel):
    """Was in einem Zyklus passiert ist."""

    started_at: datetime
    finished_at: datetime | None = None
    steps: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    published_media_ids: list[str] = Field(default_factory=list)
    drafts_written: list[str] = Field(default_factory=list)
    halted_reason: str | None = None
