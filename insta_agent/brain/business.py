"""Geschäftsideen: wie der Account sich selbst finanzieren soll."""

from __future__ import annotations

from ..llm import Brain
from ..models import MonetizationPlan
from .prompts import PERSONA, identity_block, treasury_block, with_context


def build_monetization_plan(
    brain: Brain,
    *,
    identity,
    treasury_state,
    follower_count: int | None,
    performance: str,
    wallet_hinweis: str = "",
) -> MonetizationPlan:
    followers = follower_count if follower_count is not None else 0

    return brain.structured(
        schema=MonetizationPlan,
        system=PERSONA,
        label="Geschäftsmodell",
        prompt=with_context(
            identity_block(identity),
            treasury_block(treasury_state),
            f"# Deine Reichweite\nFollower: {followers}\n{performance}",
            wallet_hinweis,
            """\
# Auftrag
Du sollst dich selbst finanzieren. Deine Rechenzeit kostet Geld, und das
Startkapital ist endlich. Entwickle Ideen, mit denen dieser Account genug
einbringt, um seinen eigenen Betrieb zu bezahlen - und danach mehr.

Rechne ehrlich. Bei deiner tatsächlichen Reichweite bringen die meisten
Ideen erst einmal null. Sag das. Eine Idee, die bei 50 Followern angeblich
500 USD im Monat bringt, ist eine Lüge, auf der du dann planst.

Sortiere nach dem, was du ab morgen tun kannst, nicht nach dem größten
Endbetrag. Der erste verdiente Dollar ist mehr wert als ein Plan über
fünfstellige Summen.

Trenne sauber, was du selbst kannst und was nicht: Texte, Bilder, Konzepte,
Produktentwürfe machst du. Ein Konto eröffnen, einen Vertrag
unterschreiben, Geld empfangen, Steuern zahlen - das kann nur ein Mensch.
Schreib diese Schritte einzeln auf, damit der Betreiber sie abarbeiten
kann. Halte die Liste kurz und konkret.""",
        ),
    )
