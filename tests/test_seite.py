"""Die Oberfläche soll sich nicht erst im Browser als kaputt erweisen.

Diese Prüfungen laufen ohne Browser und fangen genau die Fehler ab, die
auf der Seite sonst still passieren: ein Tippfehler in einer Element-Kennung
lässt `document.getElementById` null liefern, und der nächste Zugriff bricht
das ganze Javascript ab - die Seite bleibt dann leer stehen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SEITE = Path(__file__).resolve().parent.parent / "insta_agent" / "web_page.html"
QUELLE = SEITE.read_text(encoding="utf-8")


def test_jede_angesprochene_kennung_gibt_es_auch():
    angesprochen = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', QUELLE))
    # Auch die Schleife über mehrere Kennungen mitnehmen.
    for block in re.findall(r'for \(const id of \[([^\]]+)\]\)', QUELLE):
        angesprochen |= set(re.findall(r'"([A-Za-z0-9_-]+)"', block))

    vorhanden = set(re.findall(r'id="([A-Za-z0-9_-]+)"', QUELLE))
    fehlend = sorted(angesprochen - vorhanden)
    assert not fehlend, f"Javascript greift auf Elemente zu, die es nicht gibt: {fehlend}"


# Diese beiden stehen fertig im HTML und werden nur ein- und ausgeblendet.
FEST_IM_HTML = {"einnahmebox", "protokollbox"}


def test_jeder_abschnitt_wird_auch_gezeichnet():
    """Ein leerer Kasten, den niemand füllt, wäre ein toter Fleck."""
    gezeichnet = set(re.findall(r'\$\("([A-Za-z0-9_-]+box)"\)\.innerHTML', QUELLE))
    kaesten = set(re.findall(r'id="([A-Za-z0-9_-]+box)"', QUELLE)) - FEST_IM_HTML
    assert not (kaesten - gezeichnet), f"Nie gefüllt: {sorted(kaesten - gezeichnet)}"


@pytest.mark.parametrize(
    "abschnitt",
    ["held", "vorhaben", "beitraege", "ideen", "chancen", "profil", "handy", "verlauf"],
)
def test_lesbare_abschnitte_werden_nicht_staendig_neu_gebaut(abschnitt):
    """Sonst klappt jedes aufgeklappte Detail nach zwei Sekunden wieder zu.

    Die Seite fragt im Takt nach neuen Daten. Würde sie dabei jedes Mal
    alles ersetzen, verlöre man mitten im Lesen die Markierung, das
    geöffnete Detail und die Bestätigung am Kopierknopf.
    """
    assert f'wenn_neu("{abschnitt}"' in QUELLE


def test_der_agent_bekommt_kein_unlesbares_dunkelblau():
    """Seine Akzentfarbe darf dunkel sein - die Seite hellt sie dann auf."""
    assert "function lesbar(" in QUELLE
    assert 'setProperty("--akzent", akzent)' in QUELLE


def test_fremder_text_wird_nie_ungeprueft_eingesetzt():
    """Captions und Fehlertexte kommen aus dem Modell, nicht von uns."""
    # Im Warnkasten wird erst escaped und danach erst verschönert.
    stelle = QUELLE.index("const text = esc(d.fehler)")
    assert "replace(/`([^`]+)`/g" in QUELLE[stelle : stelle + 200]


def test_die_seite_sagt_wie_der_weg_zum_beitrag_gerade_laeuft():
    """Drei Schalter, drei Sätze - der Betreiber soll nicht raten müssen."""
    assert "function arbeitsweise(d)" in QUELLE
    for zustand in ["malt_selbst", "freigabe_noetig", "kann_posten"]:
        assert f"d.{zustand}" in QUELLE


def test_der_autopilot_wird_sichtbar_gemacht():
    """Wer die Freigabe abschaltet, muss das auf der Seite sehen."""
    stelle = QUELLE.index("function arbeitsweise(d)")
    abschnitt = QUELLE[stelle : stelle + 900]
    assert "Autopilot" in abschnitt
    assert 'class="warnung"' in abschnitt
