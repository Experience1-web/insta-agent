"""Aus einem kurzlebigen Token alles machen, was der Agent zum Posten braucht.

Metas Entwicklerseite gibt einem einen Token, der nach ein bis zwei
Stunden abläuft, und verrät nicht, welche Nummer das Instagram-Konto
hat. Beides von Hand nachzuholen bedeutet drei weitere Anfragen über
eine Oberfläche, die dafür nicht gemacht ist.

Diese Schritte laufen hier automatisch ab:

  kurzlebiger Token
      -> langlebiger Nutzer-Token (rund 60 Tage)
      -> die Facebook-Seite und ihr Seiten-Token
      -> die Nummer des Instagram-Kontos
      -> Gegenprobe: Wie heißt das Konto wirklich?

Der Seiten-Token ist der, der am Ende in die .env gehört: Er ist aus
einem langlebigen Nutzer-Token abgeleitet und läuft dann nicht mehr von
selbst ab, solange das Passwort steht und die App lebt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .client import GRAPH_BASE

log = logging.getLogger(__name__)


# Was der Agent braucht - und wozu. Die Reihenfolge ist die der
# Wichtigkeit: Ohne die ersten beiden kann er nichts, ohne die dritte
# lernt er nichts.
NOETIGE_RECHTE = {
    "instagram_basic": "das Konto überhaupt sehen",
    "instagram_content_publish": "Beiträge veröffentlichen",
    "instagram_manage_insights": "Reichweite und Speicherungen lesen",
    "pages_show_list": "die verknüpfte Facebook-Seite finden",
    "pages_read_engagement": "die Seite auslesen",
}

# Meta hat die Instagram-Berechtigungen umbenannt, als die Anmeldung
# über Instagram selbst dazukam. Beide Familien gibt es weiter, je
# nachdem wie die App angelegt wurde - und sie tun dasselbe. Wer die
# neuen Namen hat, soll hier nicht hören, ihm fehle etwas.
GLEICHWERTIG = {
    "instagram_basic": ("instagram_business_basic",),
    "instagram_content_publish": ("instagram_business_content_publish",),
    "instagram_manage_insights": ("instagram_business_manage_insights",),
}


@dataclass(slots=True)
class Zugang:
    """Alles, was der Agent zum Veröffentlichen braucht."""

    ig_user_id: str
    seiten_token: str
    seiten_name: str
    handle: str
    follower: int
    erteilt: tuple[str, ...] = ()
    """Welche Berechtigungen der Token wirklich hat."""

    @property
    def fehlend(self) -> tuple[str, ...]:
        """Was fehlt. Leer heißt: alles da.

        Wichtig, weil Meta fehlende Rechte nicht meldet, sondern die
        betroffenen Felder einfach weglässt. Ohne diese Gegenprobe merkt
        man es erst Wochen später an leeren Kennzahlen.
        """
        vorhanden = set(self.erteilt)
        return tuple(
            recht
            for recht in NOETIGE_RECHTE
            if recht not in vorhanden
            and not vorhanden.intersection(GLEICHWERTIG.get(recht, ()))
        )


class Einrichtungsfehler(RuntimeError):
    """Etwas fehlt oder stimmt nicht - mit einem Satz, der weiterhilft."""


def _hole(client: httpx.Client, pfad: str, **params: str) -> dict:
    antwort = client.get(f"{GRAPH_BASE}/{pfad}", params=params)
    daten = antwort.json() if antwort.content else {}
    if fehler := daten.get("error"):
        raise Einrichtungsfehler(_uebersetze(fehler))
    if antwort.status_code >= 400:
        raise Einrichtungsfehler(f"Meta antwortete mit {antwort.status_code}: {antwort.text[:200]}")
    return daten


def _uebersetze(fehler: dict) -> str:
    """Macht aus Metas Fehlermeldungen einen Satz, der sagt, was zu tun ist."""
    code = fehler.get("code")
    meldung = fehler.get("message", "")

    if code == 190:
        return (
            "Der Token ist abgelaufen oder ungültig. Hol dir im Graph-API-Explorer "
            "einen frischen und versuch es gleich danach nochmal - er hält nur "
            "ein bis zwei Stunden."
        )
    if code == 104:
        return "Es wurde gar kein Token mitgeschickt."
    if code in (100, 200, 803):
        return (
            f"Meta verweigert den Zugriff: {meldung}\n"
            "Meistens fehlt eine Berechtigung. Im Graph-API-Explorer müssen "
            "instagram_basic, instagram_content_publish, instagram_manage_insights, "
            "pages_show_list und pages_read_engagement angehakt sein."
        )
    return f"Meta meldet: {meldung}"


def richte_ein(kurzer_token: str, app_id: str, app_secret: str) -> Zugang:
    """Macht aus dem Token des Explorers einen dauerhaften Zugang."""
    with httpx.Client(timeout=30.0) as client:
        # 1. Kurzlebig gegen langlebig tauschen.
        lang = _hole(
            client,
            "oauth/access_token",
            grant_type="fb_exchange_token",
            client_id=app_id,
            client_secret=app_secret,
            fb_exchange_token=kurzer_token,
        ).get("access_token")
        if not lang:
            raise Einrichtungsfehler(
                "Der Tausch in einen langlebigen Token hat nichts zurückgegeben. "
                "Stimmen App-ID und App-Geheimnis?"
            )
        log.info("Langlebiger Nutzer-Token erhalten")

        # 1b. Nachsehen, was dieser Token überhaupt darf. Meta beschwert
        # sich nicht über fehlende Rechte - es liefert die Felder dann
        # einfach nicht.
        erteilt = tuple(
            str(e["permission"])
            for e in (_hole(client, "me/permissions", access_token=lang).get("data") or [])
            if e.get("status") == "granted"
        )

        # 2. Welche Seiten verwaltet dieser Mensch?
        seiten = _hole(client, "me/accounts", access_token=lang).get("data") or []
        if not seiten:
            raise Einrichtungsfehler(
                "Zu diesem Konto gehört keine Facebook-Seite. Leg eine an und "
                "verknüpfe sie mit dem Instagram-Konto."
            )

        # 3. Die Seite finden, an der ein Instagram-Konto hängt.
        for seite in seiten:
            seiten_token = seite.get("access_token")
            if not seiten_token:
                continue
            angehaengt = _hole(
                client,
                str(seite["id"]),
                fields="instagram_business_account",
                access_token=seiten_token,
            ).get("instagram_business_account")
            if not angehaengt:
                continue

            ig_id = str(angehaengt["id"])

            # 4. Gegenprobe: Ist das wirklich das erwartete Konto?
            konto = _hole(
                client,
                ig_id,
                fields="username,followers_count",
                access_token=seiten_token,
            )
            return Zugang(
                ig_user_id=ig_id,
                seiten_token=str(seiten_token),
                seiten_name=str(seite.get("name", "")),
                handle=str(konto.get("username", "")),
                follower=int(konto.get("followers_count", 0)),
                erteilt=erteilt,
            )

    namen = ", ".join(str(s.get("name", "?")) for s in seiten)
    raise Einrichtungsfehler(
        f"An keiner deiner Seiten ({namen}) hängt ein Instagram-Konto.\n"
        "Verknüpfe die Seite mit dem Konto: facebook.com/settings/?tab=linked_instagram"
    )
