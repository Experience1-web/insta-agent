"""Von Hand: das vorige Bild zurückholen und nur den Text ändern.

Zwei Wünsche aus dem Betrieb: Wer ein Bild erneuert und das alte doch
besser fand, soll es zurückbekommen. Und wer nur ein Wort auf einer
Karte ändern will - "versteckte" statt "vergrub" -, soll dafür keine
neue Bildsuche und keine KI bezahlen.
"""

from __future__ import annotations

import json

from PIL import Image

from insta_agent.models import Befund, Karte, PostDraft, Pruefbericht
from test_cycle import agent, settings  # noqa: F401 - Fixtures


def _beitrag_mit_karten(agent, tmp_path, n=2):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    zeile = agent.store.get_post(post_id)
    draft = PostDraft.model_validate(json.loads(zeile["draft_json"]))
    draft.karten = [Karte(text=f"Karte {i}", bildwunsch="dark field") for i in range(n)]
    agent.store.setze_entwurfsdaten(post_id, draft)
    bilder = []
    for i in range(n):
        roh = agent.settings.media_dir / f"test-k{i + 2}-echt.jpg"
        Image.new("RGB", (1080, 1350), (40 + i * 30, 60, 80)).save(roh)
        fertig = agent.settings.media_dir / f"test-k{i + 2}.png"
        Image.new("RGB", (1080, 1350), (10, 10, 10)).save(fertig)
        bilder.append(str(fertig))
    agent.store.setze_karussell(post_id, bilder)
    return post_id


def _draft(agent, post_id):
    return PostDraft.model_validate(json.loads(agent.store.get_post(post_id)["draft_json"]))


def test_nur_den_text_einer_karte_aendern_kostet_nichts(agent, tmp_path):
    post_id = _beitrag_mit_karten(agent, tmp_path)
    vorher = list(agent.brain.aufrufe)
    altes_bild = json.loads(agent.store.get_post(post_id)["karussell_json"])[0]

    ergebnis = agent.text_aendern(post_id, 2, "Versteckt unter dem Fundament")

    assert ergebnis["ok"], ergebnis
    assert agent.brain.aufrufe == vorher  # keine KI
    assert _draft(agent, post_id).karten[0].text == "Versteckt unter dem Fundament"
    neues_bild = json.loads(agent.store.get_post(post_id)["karussell_json"])[0]
    assert neues_bild != altes_bild
    # Auf das Grundbild daneben gesetzt, nicht als Schriftfläche
    assert agent._kartenroh(post_id, 0, altes_bild).name == "test-k2-echt.jpg"


def test_vorheriges_holt_bild_und_text_zurueck(agent, tmp_path):
    post_id = _beitrag_mit_karten(agent, tmp_path)
    altes_bild = json.loads(agent.store.get_post(post_id)["karussell_json"])[0]
    agent.text_aendern(post_id, 2, "Neuer Text")
    assert agent.verlauf_laengen(post_id)["2"] == 1

    ergebnis = agent.vorheriges_bild(post_id, 2)

    assert ergebnis["ok"], ergebnis
    assert json.loads(agent.store.get_post(post_id)["karussell_json"])[0] == altes_bild
    assert _draft(agent, post_id).karten[0].text == "Karte 0"
    assert agent.verlauf_laengen(post_id)["2"] == 0
    assert not agent.vorheriges_bild(post_id, 2)["ok"]


def test_titeltext_aendern_und_zurueck(agent, tmp_path):
    post_id = _beitrag_mit_karten(agent, tmp_path)
    zeile = agent.store.get_post(post_id)
    alter_text, altes_bild = _draft(agent, post_id).bildtext, zeile["image_path"]

    assert agent.text_aendern(post_id, 1, "409 Goldmünzen unter einem Haus")["ok"]
    assert _draft(agent, post_id).bildtext == "409 Goldmünzen unter einem Haus"
    assert agent.store.get_post(post_id)["image_path"] != altes_bild

    assert agent.vorheriges_bild(post_id, 1)["ok"]
    assert agent.store.get_post(post_id)["image_path"] == altes_bild
    assert _draft(agent, post_id).bildtext == alter_text


def test_bild_neu_laesst_das_alte_zurueckholen(agent, tmp_path):
    post_id = _beitrag_mit_karten(agent, tmp_path)
    altes_bild = agent.store.get_post(post_id)["image_path"]

    agent.bild_neu(post_id)
    assert agent.store.get_post(post_id)["image_path"] != altes_bild

    assert agent.vorheriges_bild(post_id, 1)["ok"]
    assert agent.store.get_post(post_id)["image_path"] == altes_bild


def test_entfernen_haelt_den_verlauf_in_der_reihe(agent, tmp_path):
    post_id = _beitrag_mit_karten(agent, tmp_path, n=3)
    agent.text_aendern(post_id, 4, "Dritte, geändert")

    agent.karte_entfernen(post_id, 2)

    # Die frühere Karte 4 ist jetzt Karte 3 - ihr Verlauf ist mitgewandert.
    assert agent.verlauf_laengen(post_id)["3"] == 1
    assert agent.vorheriges_bild(post_id, 3)["ok"]
    assert _draft(agent, post_id).karten[1].text == "Karte 2"


def test_bildunterschrift_von_hand(agent, tmp_path):
    post_id = _beitrag_mit_karten(agent, tmp_path)

    assert agent.bildunterschrift_aendern(post_id, "Neue Unterschrift.\n\nZweiter Absatz.")["ok"]

    zeile = agent.store.get_post(post_id)
    assert zeile["caption"] == "Neue Unterschrift.\n\nZweiter Absatz."
    assert _draft(agent, post_id).caption == zeile["caption"]
    assert not agent.bildunterschrift_aendern(post_id, "   ")["ok"]


def test_nach_handarbeit_laesst_sich_guenstig_neu_pruefen(agent, tmp_path):
    post_id = _beitrag_mit_karten(agent, tmp_path)
    agent.store.set_pruefung(post_id, Pruefbericht(
        urteil="freigabe", zusammenfassung="ok", mit_suche=True,
        befunde=[Befund(behauptung="x", urteil="belegt", begruendung="y")],
    ))
    assert not agent.pruefe_nach(post_id)["ok"]  # schon geprüft

    agent.text_aendern(post_id, 2, "Von Hand geändert")
    agent.brain.gesucht.clear()
    ergebnis = agent.pruefe_nach(post_id)

    assert ergebnis["ok"], ergebnis
    assert "Nachprüfung" in agent.brain.aufrufe
    assert agent.brain.gesucht == []  # ohne Websuche
    assert not agent.store.get_json(f"handgeaendert:{post_id}")


def test_zu_langer_oder_leerer_text_wird_abgelehnt(agent, tmp_path):
    post_id = _beitrag_mit_karten(agent, tmp_path)
    assert not agent.text_aendern(post_id, 2, "  ")["ok"]
    assert not agent.text_aendern(post_id, 2, "x" * 200)["ok"]
