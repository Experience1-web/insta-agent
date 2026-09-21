"""Was ein Modell taugt und was es kostet - vor der Wahl, nicht danach.

Neun Kennungen in einer Auswahlliste sind keine Entscheidungsgrundlage.
"Opus 5" sagt nichts darueber, ob es das Doppelte oder das Zehnfache
kostet und ob es an dieser Stelle ueberhaupt etwas bringt.
"""

from __future__ import annotations

import pytest

from insta_agent.economy.modelle import (
    STECKBRIEFE,
    faktor,
    kosten_eines_aufrufs,
    uebersicht,
)
from insta_agent.economy.pricing import PRICING


def test_jedes_bezahlbare_modell_hat_einen_steckbrief():
    """Sonst steht im Dashboard ein Name ohne jede Einordnung.

    Waehlbar ist, wofuer ein Preis hinterlegt ist. Kommt ein Modell zur
    Preistabelle dazu, ohne dass jemand den Steckbrief nachtraegt, faellt
    das hier auf - und nicht erst dem Betreiber vor der Auswahlliste.
    """
    fehlend = sorted(set(PRICING) - set(STECKBRIEFE))
    assert not fehlend, f"Ohne Steckbrief: {fehlend}"


def test_kein_steckbrief_ohne_preis():
    """Andersherum genauso: Was nichts kostet, gibt es nicht."""
    ueberzaehlig = sorted(set(STECKBRIEFE) - set(PRICING))
    assert not ueberzaehlig, f"Ohne Preis: {ueberzaehlig}"


def test_der_faktor_rechnet_sich_im_kopf():
    """Die Zahl, auf die es beim Vergleichen ankommt.

    Zwei Tokenpreise sagen niemandem, ob sich ein Wechsel lohnt. Ein
    Faktor schon - und er muss stimmen: Haiku ist der Bezugspunkt,
    Sonnet 5 kostet das Doppelte, Opus das Fuenffache.
    """
    assert faktor("claude-haiku-4-5") == pytest.approx(1.0)
    assert faktor("claude-sonnet-5") == pytest.approx(2.0)
    assert faktor("claude-opus-5") == pytest.approx(5.0)
    assert faktor("claude-fable-5-1") == pytest.approx(10.0)


def test_unbekanntes_modell_bekommt_keinen_faktor():
    assert faktor("gibt-es-nicht") == 0.0


def test_die_liste_ist_nach_preis_sortiert():
    """Alphabetisch steht Fable vor Haiku vor Opus - das bedeutet nichts.

    Wer eine Rolle umstellt, vergleicht Preise. Also stehen sie in der
    Reihenfolge da, in der man sie vergleicht.
    """
    cent = [z["cent_je_aufruf"] for z in uebersicht()]
    assert cent == sorted(cent)
    assert uebersicht()[0]["id"] == "claude-haiku-4-5"


def test_derselbe_auftrag_auf_jedem_modell():
    """Die Zahl, nach der gefragt wurde.

    "5/25 $ je Mio Token" beantwortet nicht, was etwas kostet. Derselbe
    Auftrag, einmal je Modell durchgerechnet, schon - und die Betraege
    muessen sich zueinander verhalten wie die Preise.
    """
    haiku = kosten_eines_aufrufs("claude-haiku-4-5", 18_000, 900)
    sonnet = kosten_eines_aufrufs("claude-sonnet-5", 18_000, 900)
    opus = kosten_eines_aufrufs("claude-opus-5", 18_000, 900)

    # 18.000 x 1 $ + 900 x 5 $, je Million.
    assert haiku == pytest.approx(0.0225)
    assert sonnet == pytest.approx(haiku * 2)
    assert opus == pytest.approx(haiku * 5)


def test_der_auftrag_ist_fuer_alle_derselbe():
    """Sonst waere der Vergleich wertlos.

    Es darf nicht passieren, dass ein Modell mit einem kleineren Auftrag
    gerechnet wird als ein anderes - dann saehe es billiger aus, ohne es
    zu sein.
    """
    zeilen = uebersicht(12_000, 700)
    fuer_hand = {
        z["id"]: round(kosten_eines_aufrufs(z["id"], 12_000, 700) * 100, 2)
        for z in zeilen
    }
    for z in zeilen:
        assert z["cent_je_aufruf"] == fuer_hand[z["id"]], z["id"]


def test_ein_groesserer_auftrag_kostet_mehr():
    """Die Rechnung haengt am eigenen Durchschnitt, nicht an einer Konstante."""
    klein = uebersicht(5_000, 300)
    gross = uebersicht(40_000, 2_000)
    je_id = {z["id"]: z["cent_je_aufruf"] for z in klein}
    for z in gross:
        assert z["cent_je_aufruf"] > je_id[z["id"]], z["id"]


def test_der_eigene_durchschnittsauftrag_wird_gemessen(tmp_path):
    """Damit gerechnet wird, was hier wirklich passiert."""
    from insta_agent.store import Store

    store = Store(tmp_path / "s.db")
    try:
        assert store.durchschnittlicher_aufruf() == (0, 0, 0)

        for ein, aus in ((10_000, 500), (20_000, 1_500)):
            store.add_ledger_entry(
                "cost", "llm", -0.03, "Stoffsuche",
                {"model": "claude-sonnet-5", "input_tokens": ein, "output_tokens": aus},
            )
        # Eine Buchung ohne Tokenzahlen darf den Schnitt nicht verwaessern.
        store.add_ledger_entry("cost", "llm", -0.01, "Alt, ohne Zahlen")

        assert store.durchschnittlicher_aufruf() == (15_000, 1_000, 2)
    finally:
        store.close()


def test_haiku_ist_als_ungeeignet_fuer_die_pruefung_gekennzeichnet():
    """Der stille Fehler, vor dem die Kennzeichnung schuetzt.

    Haiku kennt die neuere Websuche nicht. Stellt jemand die Endpruefung
    darauf um, prueft sie weiter - nur schlechter, ohne dass irgendwo ein
    Fehler erscheint. Genau deshalb muss es vor der Wahl dastehen.
    """
    assert STECKBRIEFE["claude-haiku-4-5"].websuche is False
    assert all(b.websuche for k, b in STECKBRIEFE.items() if k != "claude-haiku-4-5")


def test_gemessene_kosten_werden_je_modell_zusammengezaehlt(tmp_path):
    """Der Faktor ist geschaetzt - das hier sind die eigenen Zahlen."""
    from insta_agent.store import Store

    store = Store(tmp_path / "s.db")
    try:
        for _ in range(3):
            store.add_ledger_entry(
                "cost",
                "llm",
                -0.02,
                "Stoffsuche (claude-sonnet-5)",
                {"model": "claude-sonnet-5", "rolle": "Stoffsuche"},
            )
        store.add_ledger_entry(
            "cost",
            "llm",
            -0.05,
            "Endpruefung (claude-opus-5)",
            {"model": "claude-opus-5", "rolle": "Endpruefung"},
        )
        # Eine aeltere Buchung ohne Modell im Vermerk: Sie fehlt lieber,
        # als dass eine Zahl aus dem Notiztext geraten wird.
        store.add_ledger_entry("cost", "llm", -0.99, "Irgendwas (claude-opus-5)")

        zahlen = store.kosten_je_modell()
        assert zahlen["claude-sonnet-5"]["aufrufe"] == 3
        assert zahlen["claude-sonnet-5"]["usd"] == pytest.approx(0.06)
        assert zahlen["claude-sonnet-5"]["schnitt_usd"] == pytest.approx(0.02)
        assert zahlen["claude-opus-5"]["usd"] == pytest.approx(0.05)
    finally:
        store.close()


def test_die_dashboard_auswahl_traegt_preis_und_steckbrief():
    """Frueher waren das blosse Kennungen - dann fehlte alles Wesentliche."""
    from insta_agent.web import WAEHLBARE_IDS, _waehlbare_modelle

    modelle, grundlage = _waehlbare_modelle()

    assert WAEHLBARE_IDS == set(PRICING)
    # Ohne eigene Buchungen wird mit dem Beispielauftrag gerechnet - und
    # das steht als Null dabei, statt eine Erfahrung vorzutaeuschen.
    assert grundlage["aufrufe"] == 0
    assert grundlage["eingabe"] > 0

    for zeile in modelle:
        assert zeile["eignung"], zeile["id"]
        assert zeile["merkmal"], zeile["id"]
        assert zeile["cent_je_aufruf"] > 0, zeile["id"]
        assert zeile["cent_je_beitrag"] > zeile["cent_je_aufruf"], zeile["id"]
