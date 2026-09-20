"""Porträts der Mannschaft.

Drei Rollen, drei Gesichter. Nicht aus Verspieltheit: Wer eine Meinung
abgibt, die einen Beitrag anhält oder einen Prompt umschreibt, soll ein
Gegenüber sein und keine Funktion. Man widerspricht einer Person leichter
als einer Ausgabe.

Erzeugt wird nach dem Selbstbild der Rolle - wie jemand sich sähe, der
diese Arbeit macht. Klappt das nicht, weil kein Bilddienst eingerichtet
ist oder das Guthaben fehlt, bleibt es beim gezeichneten Zeichen aus
Initialen und Farben. Ein fehlendes Porträt ist kein Grund, irgendetwas
aufzuhalten.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Gemeinsam für alle drei, damit sie nach derselben Hand aussehen. Ohne
# das wirken sie wie drei Bilder aus drei Stockfoto-Beständen.
STIL = (
    "square crop, head and shoulders, single person, no text, no logo, "
    "no watermark, restrained colour grading, photographic, not illustration, "
    "not 3d render"
)


def portraitpfad(media_dir: Path, schluessel: str) -> Path:
    return Path(media_dir) / f"_portrait_{schluessel}.png"


def portraitwunsch(rolle, identitaet=None, bildwunsch: str = "") -> str:
    """Der Prompt für ein Porträt dieser Rolle.

    Beim Chef fließt die Bildsprache des Accounts ein: Er ist das Gesicht
    dieses Vorhabens, nicht irgendeiner Firma.

    `bildwunsch` ist, was der Betreiber selbst eingetragen hat. Das sticht
    die Voreinstellung: Das Bildmodell weiß nichts über die Person hinter
    dem Namen, und wer mit dem Ergebnis leben muss, darf es bestimmen.
    """
    teile = [bildwunsch.strip() or rolle.bildwunsch]
    if rolle.schluessel == "chef" and identitaet is not None:
        teile.append(f"colour mood taken from: {identitaet.visual_identity}")
    teile.append(STIL)
    return ", ".join(t.strip(" ,") for t in teile if t and t.strip())


def erzeuge_portrait(generator, rolle, ziel: Path, identitaet=None, bildwunsch: str = "") -> Path | None:
    """Malt ein Porträt. None heisst: hat nicht geklappt, Zeichen bleibt."""
    pfad, _grund = male_portrait(generator, rolle, ziel, identitaet, bildwunsch)
    return pfad


def male_portrait(
    generator, rolle, ziel: Path, identitaet=None, bildwunsch: str = ""
) -> tuple[Path | None, str]:
    """Wie erzeuge_portrait, gibt aber den Grund des Fehlschlags mit zurück.

    Der Grund gehört dem Betreiber: "hat nicht geklappt" lässt ihn raten,
    ob der Schlüssel fehlt, das Tageslimit erreicht ist oder das Netz weg
    war. Jede dieser Ursachen braucht eine andere Reaktion.
    """
    if generator is None:
        return None, "Kein Bilddienst eingerichtet"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    try:
        return generator.erzeuge(portraitwunsch(rolle, identitaet, bildwunsch), ziel), ""
    except Exception as exc:  # noqa: BLE001 - der Grund gehört zum Ergebnis
        log.warning("Porträt für %s nicht erzeugt: %s", rolle.schluessel, exc)
        return None, str(exc)
