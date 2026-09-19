"""API-Fehler müssen als Klartext ankommen, nicht als Traceback.

Wenn das Guthaben fehlt oder der Schlüssel nicht stimmt, soll der Agent
sagen, was zu tun ist - nicht mit einem Python-Fehler abstürzen.
"""

import httpx
import pytest
from anthropic import APIStatusError

from insta_agent.runner import _erklaere_api_fehler


def _fehler(status: int, nachricht: str = "error") -> APIStatusError:
    antwort = httpx.Response(
        status_code=status,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        json={"error": {"message": nachricht}},
    )
    return APIStatusError(nachricht, response=antwort, body=None)


def test_falscher_schluessel_wird_erklaert():
    text = _erklaere_api_fehler(_fehler(401, "invalid x-api-key"))
    assert "Schlüssel" in text
    assert "insta-agent setup" in text


def test_fehlendes_guthaben_wird_erklaert():
    text = _erklaere_api_fehler(_fehler(400, "Your credit balance is too low"))
    assert "Guthaben" in text
    assert "Billing" in text
    # Der Hinweis muss die interne Kasse von der echten Abrechnung trennen.
    assert "Kasse des Agenten" in text


def test_zu_viele_anfragen_wird_erklaert():
    assert "Warte" in _erklaere_api_fehler(_fehler(429, "rate limit"))


def test_serverfehler_wird_nicht_dem_nutzer_angelastet():
    text = _erklaere_api_fehler(_fehler(503, "overloaded"))
    assert "nicht an dir" in text


def test_ein_400_ohne_guthabenbezug_bleibt_unterscheidbar():
    """Nicht jeder 400 ist ein Guthabenproblem."""
    text = _erklaere_api_fehler(_fehler(400, "invalid request: bad model"))
    assert "Guthaben" not in text
    assert "400" in text
