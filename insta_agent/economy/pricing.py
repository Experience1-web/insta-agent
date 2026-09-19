"""Preistabelle der Claude API, damit der Agent seine eigenen Kosten kennt.

Preise in USD pro 1 Mio Token, Stand 2026-06. Wenn sich die Preise ändern,
ist das hier der einzige Ort, der angefasst werden muss.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    # Cache-Treffer sind deutlich billiger als frische Eingabe-Token.
    cache_read_per_mtok: float
    cache_write_per_mtok: float


PRICING: dict[str, ModelPrice] = {
    "claude-fable-5-1": ModelPrice(10.00, 50.00, 1.00, 12.50),
    "claude-fable-5": ModelPrice(10.00, 50.00, 1.00, 12.50),
    "claude-opus-5": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-7": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-6": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5": ModelPrice(2.00, 10.00, 0.20, 2.50),
    "claude-sonnet-4-6": ModelPrice(3.00, 15.00, 0.30, 3.75),
    "claude-haiku-4-5": ModelPrice(1.00, 5.00, 0.10, 1.25),
}

# Wenn ein unbekanntes Modell auftaucht, lieber zu teuer schätzen als zu
# billig - eine Unterschätzung würde die Budgetbremse aushebeln.
_FALLBACK_PRICE = ModelPrice(10.00, 50.00, 1.00, 12.50)


def price_for(model: str) -> ModelPrice:
    return PRICING.get(model, _FALLBACK_PRICE)


def cost_of_usage(model: str, usage: object) -> float:
    """Rechnet ein usage-Objekt der Anthropic-Antwort in USD um."""
    price = price_for(model)

    def field(name: str) -> int:
        return int(getattr(usage, name, 0) or 0)

    fresh_input = field("input_tokens")
    output = field("output_tokens")
    cache_read = field("cache_read_input_tokens")
    cache_write = field("cache_creation_input_tokens")

    return (
        fresh_input * price.input_per_mtok
        + output * price.output_per_mtok
        + cache_read * price.cache_read_per_mtok
        + cache_write * price.cache_write_per_mtok
    ) / 1_000_000
