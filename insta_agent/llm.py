"""Der Zugang zum Modell - mit eingebauter Kostenerfassung.

Jeder Aufruf wird sofort in USD umgerechnet und in der Kasse gebucht. Der
Agent weiß dadurch jederzeit, was sein eigenes Denken gerade kostet, und
kann sich selbst drosseln, bevor das Budget weg ist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from .config import LLMConfig
from .economy.ledger import Mode, Treasury
from .economy.pricing import cost_of_usage

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Nicht jedes Modell kennt die Aufwandsstufe. Haiku 4.5 und die 4.5er
# Sonnets lehnen sie mit einem 400er ab. Deshalb eine Positivliste: Bei
# einem unbekannten Modell wird der Parameter weggelassen, was höchstens
# die Voreinstellung bedeutet - und nicht den Abbruch des Zyklus.
EFFORT_MODELLE = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)


def unterstuetzt_effort(model: str) -> bool:
    return model.startswith(EFFORT_MODELLE)


# Server-seitige Websuche. Läuft bei Anthropic, es gibt nichts selbst
# auszuführen; die Ergebnisse kommen als Blöcke in derselben Antwort.
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 6,
}


class ModelRefused(RuntimeError):
    """Das Modell hat die Anfrage abgelehnt - auch beim Ausweichmodell."""


@dataclass(slots=True)
class CallResult:
    text: str
    cost_usd: float
    model: str
    sources: list[str]


class Brain:
    def __init__(self, config: LLMConfig, treasury: Treasury, api_key: str | None = None) -> None:
        self.config = config
        self.treasury = treasury
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    # -- Modellwahl --------------------------------------------------------

    def _output_config(self, model: str) -> dict[str, Any] | None:
        """Die Aufwandsstufe nur dort mitschicken, wo sie akzeptiert wird."""
        return {"effort": self.config.effort} if unterstuetzt_effort(model) else None

    def _model_for(self, task: str) -> str:
        """Im Sparbetrieb läuft alles auf dem günstigen Modell."""
        if self.treasury.state().mode is Mode.FRUGAL:
            return self.config.cheap_model
        return self.config.cheap_model if task == "routine" else self.config.model

    def _book(self, model: str, response: Any, label: str) -> float:
        cost = cost_of_usage(model, response.usage)
        self.treasury.charge(
            cost,
            category="llm",
            note=f"{label} ({model})",
            meta={
                "input_tokens": getattr(response.usage, "input_tokens", 0),
                "output_tokens": getattr(response.usage, "output_tokens", 0),
            },
        )
        log.debug("%s auf %s: %.5f USD", label, model, cost)
        return cost

    @staticmethod
    def _refused(response: Any) -> bool:
        return getattr(response, "stop_reason", None) == "refusal"

    # -- Strukturierte Antworten ------------------------------------------

    def structured(
        self,
        *,
        schema: type[T],
        system: str,
        prompt: str,
        label: str,
        task: str = "reasoning",
    ) -> T:
        """Holt eine validierte Antwort nach dem Pydantic-Schema."""
        self.treasury.check()
        model = self._model_for(task)

        for attempt_model in (model, self.config.fallback_model):
            kwargs: dict[str, Any] = {
                "model": attempt_model,
                "max_tokens": self.config.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
                "output_format": schema,
            }
            if konfig := self._output_config(attempt_model):
                kwargs["output_config"] = konfig

            response = self.client.messages.parse(**kwargs)
            self._book(attempt_model, response, label)
            if self._refused(response):
                log.warning("%s wurde von %s abgelehnt, weiche aus", label, attempt_model)
                continue
            parsed = response.parsed_output
            if parsed is not None:
                return parsed
            log.warning("%s lieferte keine verwertbare Struktur, versuche Ausweichmodell", label)

        raise ModelRefused(f"{label}: weder {model} noch {self.config.fallback_model} lieferten ein Ergebnis.")

    # -- Freie Antworten, optional mit Websuche ---------------------------

    def text(
        self,
        *,
        system: str,
        prompt: str,
        label: str,
        task: str = "reasoning",
        web_search: bool = False,
        max_rounds: int = 6,
    ) -> CallResult:
        """Ein Textaufruf. Mit web_search recherchiert das Modell selbst."""
        self.treasury.check()
        model = self._model_for(task)
        tools = [WEB_SEARCH_TOOL] if web_search else []

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        total_cost = 0.0
        sources: list[str] = []
        pieces: list[str] = []

        for _ in range(max_rounds):
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": self.config.max_tokens,
                "system": system,
                "messages": messages,
            }
            if konfig := self._output_config(model):
                kwargs["output_config"] = konfig
            if tools:
                kwargs["tools"] = tools

            response = self.client.messages.create(**kwargs)
            total_cost += self._book(model, response, label)

            if self._refused(response):
                raise ModelRefused(f"{label}: {getattr(response, 'stop_details', None)}")

            pieces.extend(b.text for b in response.content if b.type == "text")
            sources.extend(_extract_sources(response.content))

            # Server-Tools können den Zug pausieren; dann einfach fortsetzen.
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                self.treasury.check()
                continue
            break

        return CallResult(
            text="\n".join(p for p in pieces if p.strip()).strip(),
            cost_usd=total_cost,
            model=model,
            sources=list(dict.fromkeys(sources)),
        )


def _extract_sources(content: list[Any]) -> list[str]:
    """Zieht die URLs aus den Blöcken der Websuche."""
    urls: list[str] = []
    for block in content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        results = getattr(block, "content", None)
        # Bei einem Fehler ist content ein einzelnes Objekt, kein Array.
        if not isinstance(results, list):
            log.warning("Websuche meldete einen Fehler: %s", getattr(results, "error_code", results))
            continue
        for result in results:
            if url := getattr(result, "url", None):
                urls.append(url)
    return urls
