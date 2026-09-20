"""Anbindung an die offizielle Instagram Graph API.

Bewusst nur der offizielle Weg. Es gibt inoffizielle Bibliotheken, die sich
als App ausgeben und Folgen/Entfolgen automatisieren - die verstoßen gegen
die Nutzungsbedingungen und kosten früher oder später den Account. Dieser
Agent wächst über Inhalte, nicht über Tricks.

Voraussetzungen:
  - Instagram Business- oder Creator-Account
  - verknüpft mit einer Facebook-Seite
  - Meta-App mit instagram_basic, instagram_content_publish,
    instagram_manage_insights
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Kennzahlen auf Kontoebene, die die Graph API für Business-Konten liefert.
ACCOUNT_METRICS = ["reach", "profile_views", "accounts_engaged"]
# Kennzahlen je Beitrag.
MEDIA_METRICS = ["reach", "likes", "comments", "saved", "shares"]


class GraphAPIError(RuntimeError):
    """Die Graph API hat einen Fehler zurückgegeben."""


# Die Berechtigung, die es für Kennzahlen braucht. Sie steckt nicht in den
# vier, die man fürs Veröffentlichen anhakt - wer sie vergisst, bekommt
# eine Fehlermeldung, die nichts darüber sagt, was fehlt.
INSIGHTS_RECHT = "instagram_manage_insights"


def kennzahlgrund(exc: Exception) -> str:
    """Übersetzt Metas Absage bei den Kennzahlen in einen brauchbaren Satz.

    "(#10) Application does not have permission for this action" sagt
    nicht, welche Erlaubnis fehlt. Ohne Kennzahlen lernt der Agent nichts
    aus seinen Beiträgen - das ist zu wichtig, um es als englische
    Fehlermeldung durchlaufen zu lassen.
    """
    text = str(exc)
    if "10:" in text or "(#10)" in text:
        return (
            "Die Berechtigung fehlt. Metas Zugang wurde ohne "
            f"{INSIGHTS_RECHT} erteilt - ohne die gibt es keine Reichweite "
            "und keine Speicherungen. Neu verbinden mit `insta-agent instagram` "
            "und diese Berechtigung mit anhaken."
        )
    if "190:" in text:
        return (
            "Das Zugangswort ist abgelaufen. Neu verbinden mit "
            "`insta-agent instagram`."
        )
    return text


@dataclass(slots=True)
class AccountSnapshot:
    followers: int
    media_count: int
    username: str | None = None


class InstagramClient:
    def __init__(self, ig_user_id: str, access_token: str, timeout: float = 30.0) -> None:
        self.ig_user_id = ig_user_id
        self.access_token = access_token
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> InstagramClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- Basis ------------------------------------------------------------

    def _request(self, method: str, path: str, **params: Any) -> dict[str, Any]:
        params["access_token"] = self.access_token
        url = f"{GRAPH_BASE}/{path.lstrip('/')}"

        if method == "GET":
            response = self._http.get(url, params=params)
        else:
            response = self._http.post(url, data=params)

        try:
            payload = response.json()
        except ValueError as exc:
            raise GraphAPIError(f"Keine gültige JSON-Antwort ({response.status_code})") from exc

        if "error" in payload:
            error = payload["error"]
            raise GraphAPIError(
                f"{error.get('type', 'Fehler')} {error.get('code', '?')}: "
                f"{error.get('message', 'unbekannt')}"
            )
        if response.status_code >= 400:
            raise GraphAPIError(f"HTTP {response.status_code}: {response.text[:300]}")
        return payload

    # -- Konto ------------------------------------------------------------

    def account(self) -> AccountSnapshot:
        data = self._request(
            "GET", self.ig_user_id, fields="username,followers_count,media_count"
        )
        return AccountSnapshot(
            followers=int(data.get("followers_count", 0)),
            media_count=int(data.get("media_count", 0)),
            username=data.get("username"),
        )

    # -- Veröffentlichen -------------------------------------------------

    def create_container(self, image_url: str, caption: str) -> str:
        """Schritt 1: Instagram lädt das Bild von der URL und legt es ab."""
        data = self._request("POST", f"{self.ig_user_id}/media", image_url=image_url, caption=caption)
        container_id = data.get("id")
        if not container_id:
            raise GraphAPIError(f"Kein Container zurückgegeben: {data}")
        return str(container_id)

    def wait_until_ready(self, container_id: str, *, attempts: int = 12, delay: float = 5.0) -> None:
        """Schritt 2: warten, bis Instagram das Bild verarbeitet hat."""
        for attempt in range(attempts):
            data = self._request("GET", container_id, fields="status_code,status")
            status = data.get("status_code")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise GraphAPIError(f"Verarbeitung fehlgeschlagen: {data.get('status')}")
            log.info("Container %s noch %s (Versuch %d)", container_id, status, attempt + 1)
            time.sleep(delay)
        raise GraphAPIError(f"Container {container_id} wurde nicht rechtzeitig fertig")

    def publish_container(self, container_id: str) -> str:
        """Schritt 3: den fertigen Container veröffentlichen."""
        data = self._request("POST", f"{self.ig_user_id}/media_publish", creation_id=container_id)
        media_id = data.get("id")
        if not media_id:
            raise GraphAPIError(f"Keine Media-ID zurückgegeben: {data}")
        return str(media_id)

    # -- Kennzahlen -------------------------------------------------------

    def media_insights(self, media_id: str) -> dict[str, float]:
        try:
            data = self._request("GET", f"{media_id}/insights", metric=",".join(MEDIA_METRICS))
        except GraphAPIError as exc:
            # Sehr frische oder sehr kleine Beiträge liefern manchmal nichts.
            log.warning("Keine Beitragskennzahlen für %s: %s", media_id, kennzahlgrund(exc))
            return {}
        return _flatten_insights(data)

    def account_insights(self, period: str = "day") -> dict[str, float]:
        try:
            data = self._request(
                "GET",
                f"{self.ig_user_id}/insights",
                metric=",".join(ACCOUNT_METRICS),
                period=period,
                metric_type="total_value",
            )
        except GraphAPIError as exc:
            log.warning("Keine Kontokennzahlen: %s", kennzahlgrund(exc))
            return {}
        return _flatten_insights(data)

    # -- Token-Pflege ------------------------------------------------------

    def refresh_long_lived_token(self, app_id: str, app_secret: str) -> tuple[str, int]:
        """Tauscht den Token gegen einen neuen, wieder ~60 Tage gültigen."""
        data = self._request(
            "GET",
            "oauth/access_token",
            grant_type="fb_exchange_token",
            client_id=app_id,
            client_secret=app_secret,
            fb_exchange_token=self.access_token,
        )
        token = data.get("access_token")
        if not token:
            raise GraphAPIError(f"Kein neuer Token erhalten: {data}")
        return str(token), int(data.get("expires_in", 0))


def _flatten_insights(payload: dict[str, Any]) -> dict[str, float]:
    """Macht aus der verschachtelten Insights-Antwort ein flaches Dict."""
    result: dict[str, float] = {}
    for entry in payload.get("data", []):
        name = entry.get("name")
        if not name:
            continue
        if (total := entry.get("total_value")) and "value" in total:
            result[name] = float(total["value"])
        elif values := entry.get("values"):
            result[name] = float(values[-1].get("value", 0))
    return result
