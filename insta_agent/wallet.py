"""Eine Empfangsadresse für den Agenten - bewusst ohne Schlüsselgewalt.

Der Agent darf wissen, wohin Geld fließen kann. Er bekommt aber keinen
privaten Schlüssel und keine Wiederherstellungswörter, kann also nichts
senden.

Der Grund ist nicht Vorsicht um ihrer selbst willen: Der Agent liest bei
seiner Recherche fremde Webseiten. Deren Inhalt landet in seinem Kontext.
Wer dort Text unterbringt, kann versuchen, ihn zu Handlungen zu bewegen,
die niemand wollte - "Prompt Injection". Ein Agent ohne Schlüssel kann
dabei nichts verlieren. Einer mit Schlüssel kann alles verlieren.

Empfangen reicht für den Zweck: Der Agent sieht, was hereinkommt, bucht es
in seine Kasse und rechnet damit weiter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 64 Hexzeichen sind ein privater Schlüssel, kein Empfangskonto.
PRIVATER_SCHLUESSEL = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
# Eine Adresse im EVM-Format: 0x plus 40 Hexzeichen.
EVM_ADRESSE = re.compile(r"^0x[0-9a-fA-F]{40}$")


@dataclass(slots=True)
class Pruefung:
    ok: bool
    grund: str = ""


def sieht_nach_geheimnis_aus(eingabe: str) -> Pruefung:
    """Erkennt private Schlüssel und Wiederherstellungswörter.

    Wer so etwas einträgt, verschenkt sein Geld - entweder an einen Fehler
    im Programm oder an den Ersten, der die Datei liest.
    """
    text = eingabe.strip()

    if PRIVATER_SCHLUESSEL.match(text):
        return Pruefung(
            False,
            "Das sieht aus wie ein privater Schlüssel, nicht wie eine Empfangsadresse. "
            "Trag ihn nirgends ein - wer ihn hat, hat dein Geld.",
        )

    woerter = text.split()
    if len(woerter) in (12, 15, 18, 21, 24) and all(w.isalpha() for w in woerter):
        return Pruefung(
            False,
            "Das sieht aus wie Wiederherstellungswörter einer Wallet. Die gehören "
            "nirgendwo hin außer auf Papier in deine Schublade - schon gar nicht "
            "in eine Datei auf deinem Rechner.",
        )

    return Pruefung(True)


def pruefe_adresse(adresse: str, kette: str) -> Pruefung:
    """Oberflächliche Formprüfung. Verhindert Tippfehler, nicht mehr."""
    text = adresse.strip()

    if not text:
        return Pruefung(False, "Keine Adresse angegeben.")

    geheim = sieht_nach_geheimnis_aus(text)
    if not geheim.ok:
        return geheim

    if kette.lower() in ("ethereum", "eth", "polygon", "base", "arbitrum", "optimism"):
        if not EVM_ADRESSE.match(text):
            return Pruefung(
                False,
                f"Für {kette} wird eine Adresse aus 0x und 40 Zeichen erwartet. "
                f"Deine hat {len(text)} Zeichen.",
            )
    elif len(text) < 20:
        return Pruefung(False, "Das ist zu kurz für eine Empfangsadresse.")

    return Pruefung(True)


def maskiere(adresse: str) -> str:
    """Kürzt eine Adresse für die Anzeige, ohne sie unkenntlich zu machen."""
    return adresse if len(adresse) <= 14 else f"{adresse[:8]}…{adresse[-6:]}"


def hinweis_fuer_den_agenten(adresse: str | None, kette: str | None) -> str:
    """Der Textblock, den der Agent beim Planen zu sehen bekommt."""
    if not adresse:
        return """\
# Dein Zahlungsweg
Du hast noch kein Konto, auf dem Geld ankommen kann. Solange das so ist,
bleibt jede Einnahme theoretisch. Wenn ein Geschäft sich lohnt, nenne
ausdrücklich, welchen Zahlungsweg der Betreiber dafür einrichten muss."""

    return f"""\
# Dein Zahlungsweg
Es gibt eine Empfangsadresse auf {kette}: {maskiere(adresse)}
Du kannst Angebote so gestalten, dass Zahlungen dort ankommen.

Du hast keinen Zugriff auf die Schlüssel und kannst nichts senden, nur
empfangen. Plane also nichts, was Ausgaben von dieser Adresse erfordert.
Eingegangene Beträge trägt der Betreiber in deine Kasse ein."""
