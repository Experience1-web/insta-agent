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
    ["kopf", "mannschaft", "vorhaben", "beitraege", "ideen", "chancen", "handy", "verlauf"],
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


def test_kostenlose_bilder_werden_nicht_als_null_dollar_ausgewiesen():
    """"0.0000 USD je Bild" liest sich wie ein Fehler, nicht wie ein Vorteil."""
    stelle = QUELLE.index("function arbeitsweise(d)")
    abschnitt = QUELLE[stelle : stelle + 700]
    assert "d.bildkosten > 0" in abschnitt
    assert "kostenloses Kontingent" in abschnitt


def test_der_starthinweis_kennt_die_lage():
    """"Veroeffentlicht wird nichts" war fest verdrahtet und wurde falsch,
    sobald alles eingerichtet war."""
    assert "Veröffentlicht wird nichts – es entstehen nur Entwürfe." not in QUELLE
    stelle = QUELLE.index('$("starthinweis").innerHTML')
    abschnitt = QUELLE[stelle : stelle + 300]
    assert "d.kann_posten" in abschnitt
    assert "Hinaus geht nur, was du freigibst" in abschnitt


# --- Popups und die Mannschaft --------------------------------------------


def test_jedes_popup_laesst_sich_wieder_schliessen():
    """Ein Fenster ohne Ausgang ist eine Sackgasse - auf dem Handy erst recht."""
    assert 'class="zu"' in QUELLE
    assert 'e.key === "Escape"' in QUELLE
    assert "if (e.target === grund) schliesse_popup();" in QUELLE


def test_das_popup_gibt_die_seite_wieder_frei():
    """Sonst bleibt die Seite gesperrt, nachdem das Fenster zu ist."""
    assert QUELLE.count('document.body.style.overflow = ""') >= 1


def test_ein_nicht_geprueftes_urteil_sieht_anders_aus_als_ein_gutes():
    """Kein Bericht ist nicht dasselbe wie ein sauberer Bericht."""
    assert "nicht geprüft" in QUELLE
    assert "ungeprueft" in QUELLE


def test_alle_urteile_der_pruefung_haben_eine_marke():
    for urteil in ("freigabe", "nachbessern", "ablehnen"):
        assert f"{urteil}:" in QUELLE or f'"{urteil}"' in QUELLE, urteil


def test_die_knoepfe_auf_der_karte_oeffnen_nicht_das_popup():
    """Sonst geht beim Freigeben gleichzeitig das Fenster auf."""
    assert 'if (e.target.closest("button, a")) return;' in QUELLE


def test_bewegung_laesst_sich_abschalten():
    """Wer Animationen ausgeschaltet hat, meint das ernst."""
    assert "prefers-reduced-motion" in QUELLE


def test_ein_laufender_zyklus_meldet_sich_zwischendurch():
    """Minutenlange Stille sieht aus wie ein haengender Agent."""
    import inspect

    from insta_agent import llm

    quelle = inspect.getsource(llm.Brain)
    assert quelle.count("denkt nach") >= 2, "structured und text sollen beide melden"


# --- Bilder statt Text ----------------------------------------------------


def test_der_kopf_zeigt_das_neueste_bild():
    """Eine Seite ueber Bilder, die selbst keine zeigt, ist ein Widerspruch."""
    assert 'class="hintergrund"' in QUELLE
    assert "mitbild" in QUELLE


def test_der_schleier_haelt_die_schrift_lesbar():
    """Ohne ihn verschwindet der Titel auf einem hellen Bild."""
    assert 'class="schleier"' in QUELLE
    assert "linear-gradient" in QUELLE


def test_die_beitraege_sind_eine_galerie():
    """Das Bild ist der Beitrag - der Text steht darunter."""
    assert "beitragsbild" in QUELLE
    assert "aspect-ratio: 4 / 5" in QUELLE


def test_ein_beitrag_ohne_bild_sagt_warum():
    """Eine leere Flaeche laesst den Betreiber raten, ob etwas kaputt ist."""
    assert "Noch kein Bild" in QUELLE
    assert "es blieb bei der Typografie" in QUELLE


def test_im_fenster_steht_das_bild_gross_oben():
    assert 'class="grossbild"' in QUELLE


# --- Kein Knopf darf stumm scheitern --------------------------------------


def test_alle_knoepfe_gehen_ueber_einen_sender():
    """Jede eigene Fassung war eine Stelle, die stumm scheitern konnte."""
    assert 'await fetch("/api/' not in QUELLE
    assert "async function sende(" in QUELLE


def test_ein_altes_dashboard_wird_als_solches_erkannt():
    """Die Seite kommt frisch von der Platte, das laufende Programm nicht.

    Nach einer Aktualisierung zeigt ein altes Dashboard deshalb Knoepfe,
    die es selbst nicht kennt - und antwortete darauf mit 404 und einer
    Textmeldung, an der das Auslesen scheiterte. Es passierte nichts.
    """
    assert "antwort.status === 404" in QUELLE
    assert "älteren Fassung als die Seite" in QUELLE


def test_auch_ein_unerreichbares_dashboard_sagt_etwas():
    assert "Das Dashboard antwortet nicht" in QUELLE
