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
    footer: str = Field(default="", description="Kleiner Fußtext, meist der Handle")


class PostDraft(BaseModel):
    """Ein fertiger Post-Entwurf."""

    pillar: str = Field(description="Zu welcher Themensäule der Post gehört")
    hook: str = Field(description="Die ersten Worte der Caption, die zum Weiterlesen zwingen")
    caption: str = Field(description="Vollständige Caption inklusive Hook, max 2200 Zeichen")
    hashtags: list[str] = Field(description="Ohne #, gemischt aus groß, mittel und klein")
    call_to_action: str = Field(description="Was der Leser tun soll")
    visual: VisualSpec
    best_time_hint: str = Field(description="Wann dieser Post laufen sollte und warum")
    expected_outcome: str = Field(description="Was der Agent sich davon verspricht")


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
