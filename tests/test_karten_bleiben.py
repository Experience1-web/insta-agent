# ruff: noqa: F811 - agent und settings sind Fixtures aus test_cycle
"""Die Texte auf den Karussell-Bildern gehen nicht verloren und werden geprüft.

Beim Goldrubel-Beitrag fehlten nach dem Nachbessern alle vier Kartentexte.
Die Bilder standen noch da, "dieses neu" meldete "Zu diesem Bild gibt es
keine Karte". Und die Endprüfung hatte die Karten nie gesehen - "Wer das
Gold vergrub, holte es nie wieder" stand ungeprüft auf Bild 5.
"""

from __future__ import annotations

import json

from insta_agent.brain.pruefung import _zu_pruefen
from insta_agent.brain.ueberarbeitung import ueberarbeite_beitrag
from insta_agent.models import Befund, Karte, PostDraft, Pruefbericht
from test_cycle import _entwurf, _identitaet, agent, settings  # noqa: F401


def _mit_karten(n: int = 3):
    draft = _entwurf()
    draft.karten = [Karte(text=f"Karte Nummer {i}") for i in range(n)]
    return draft


class _Brain:
    def __init__(self, antwort):
        self.antwort = antwort
        self.prompt = ""

    def structured(self, **kwargs):
        self.prompt = kwargs["prompt"]
        return self.antwort


def _bericht():
    return Pruefbericht(
        urteil="nachbessern",
        zusammenfassung="x",
        befunde=[Befund(behauptung="a", urteil="ungenau", begruendung="b")],
    )


def test_die_endpruefung_sieht_die_kartentexte():
    text = _zu_pruefen(_mit_karten())

    assert "Bild 2: Karte Nummer 0" in text
    assert "Bild 4: Karte Nummer 2" in text


def test_kommen_die_karten_nicht_zurueck_bleiben_die_alten():
    alt = _mit_karten()
    ohne = _entwurf()  # das Modell liefert keine Karten
    brain = _Brain(ohne)

    neu = ueberarbeite_beitrag(
        brain, identity=_identitaet(), strategy=None, draft=alt, bericht=_bericht()
    )

    assert [k.text for k in neu.karten] == [k.text for k in alt.karten]
    assert "Bild 3: Karte Nummer 1" in brain.prompt


def test_eine_korrigierte_karte_bleibt_korrigiert():
    alt = _mit_karten()
    antwort = _mit_karten()
    antwort.karten[1].text = "Korrigiert"

    neu = ueberarbeite_beitrag(
        _Brain(antwort), identity=_identitaet(), strategy=None, draft=alt, bericht=_bericht()
    )

    assert neu.karten[1].text == "Korrigiert"


def test_verlorene_karten_kommen_aus_der_ablage_zurueck(agent):
    agent.run_cycle()
    post = agent.store.pending_drafts()[0]
    post_id = post["id"]
    voll = _mit_karten(2)
    voll.image_generation_prompt = "ein ganz bestimmter prompt"
    agent.store.setze_karussell(post_id, ["/nirgends/a.png", "/nirgends/b.png"])

    # So sah der Entwurf nach dem alten Nachbessern aus: Karten weg.
    leer = voll.model_copy(update={"karten": []})
    agent.store.setze_entwurfsdaten(post_id, leer)
    ablage = agent.settings.draft_dir
    ablage.mkdir(parents=True, exist_ok=True)
    (ablage / "20990101-000000-alt.md").write_text(
        "# Entwurf\n\n```json\n" + json.dumps(voll.model_dump(mode="json")) + "\n```\n",
        encoding="utf-8",
    )

    ergebnis = agent.karte_neu(post_id, 3)

    assert ergebnis["ok"], ergebnis
    daten = json.loads(agent.store.get_post(post_id)["draft_json"])
    assert [k["text"] for k in daten["karten"]] == ["Karte Nummer 0", "Karte Nummer 1"]


def test_ohne_ablage_sagt_karte_neu_was_los_ist(agent):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    agent.store.setze_karussell(post_id, ["/nirgends/a.png"])
    leer = _entwurf()
    leer.image_generation_prompt = "gibt es nirgends"
    agent.store.setze_entwurfsdaten(post_id, leer)

    ergebnis = agent.karte_neu(post_id, 2)

    assert not ergebnis["ok"]
    assert "verloren" in ergebnis["grund"]


def test_nachbessern_macht_nur_geaenderte_karten_neu(agent, monkeypatch):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    alt = _mit_karten(3)
    agent.store.setze_entwurfsdaten(post_id, alt)
    agent.store.setze_karussell(post_id, ["/a.png", "/b.png", "/c.png"])
    agent.store.set_pruefung(post_id, _bericht())

    neu = _mit_karten(3)
    neu.karten[2].text = "Korrigiert"
    monkeypatch.setattr("insta_agent.runner.ueberarbeite_beitrag", lambda *a, **k: neu)
    erneuert = []
    monkeypatch.setattr(
        agent, "_karte_erneuern", lambda pid, d, b, versatz, i, **k: erneuert.append(versatz)
    )

    ergebnis = agent.nachbessern(post_id)

    assert ergebnis["ok"]
    assert erneuert == [2]


def test_karte_entfernen_nimmt_bild_und_text_heraus(agent):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    agent.store.setze_entwurfsdaten(post_id, _mit_karten(3))
    agent.store.setze_karussell(post_id, ["/a.png", "/b.png", "/c.png"])

    ergebnis = agent.karte_entfernen(post_id, 3)

    assert ergebnis["ok"]
    zeile = agent.store.get_post(post_id)
    assert json.loads(zeile["karussell_json"]) == ["/a.png", "/c.png"]
    assert [k["text"] for k in json.loads(zeile["draft_json"])["karten"]] == [
        "Karte Nummer 0",
        "Karte Nummer 2",
    ]
    assert not agent.karte_entfernen(post_id, 1)["ok"]


def test_nach_dem_nachbessern_liegt_die_alte_fassung_im_protokoll(agent, monkeypatch):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    agent.store.setze_entwurfsdaten(post_id, _mit_karten(2))
    agent.store.setze_karussell(post_id, ["/a.png", "/b.png"])
    agent.store.set_pruefung(post_id, _bericht())
    # So hat das alte Nachbessern den Entwurf hinterlassen: ohne Karten.
    monkeypatch.setattr(
        "insta_agent.runner.ueberarbeite_beitrag", lambda *a, **k: _entwurf()
    )
    agent.nachbessern(post_id)
    assert json.loads(agent.store.get_post(post_id)["draft_json"])["karten"] == []

    ohne = PostDraft.model_validate(json.loads(agent.store.get_post(post_id)["draft_json"]))
    assert agent._karten_wiederfinden(post_id, ohne, 2)
    assert len(json.loads(agent.store.get_post(post_id)["draft_json"])["karten"]) == 2


class _Maler:
    name = "maler"

    def erzeuge(self, prompt, ziel):
        from PIL import Image

        Image.new("RGB", (1080, 1350), (24, 28, 40)).save(ziel)
        return ziel


def test_dieses_neu_im_dashboard_stuerzt_beim_malen_nicht_ab(agent, settings, monkeypatch):
    """Die Knöpfe bauen einen frischen Agenten ohne Zyklus. Dem fehlte der
    Zustand der Bildsuche, und "dieses neu" brach ab, sobald gemalt wurde."""
    from insta_agent.runner import Agent

    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    draft = _mit_karten(2)
    for karte in draft.karten:
        karte.bildsuche = ""
        karte.bildwunsch = "a quiet dark field"
    agent.store.setze_entwurfsdaten(post_id, draft)
    agent.store.setze_karussell(post_id, ["/a.png", "/b.png"])

    frisch = Agent(settings)  # wie im Dashboard: kein run_cycle vorher
    frisch.bildgenerator = _Maler()
    try:
        ergebnis = frisch.karte_neu(post_id, 2)
    finally:
        frisch.close()

    assert ergebnis["ok"], ergebnis
    assert ergebnis["gemalt"] is True


def test_dieses_neu_beurteilt_gegen_den_fund_nicht_gegen_das_suchwort(agent, monkeypatch):
    """Sonst passt jede Grabung zu "excavation" - so kam Kreta ins Titelbild."""
    import insta_agent.imaging.echtbild as echtbild
    from test_stoff import _schwach

    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    draft = _mit_karten(1)
    draft.karten[0].bildsuche = "archaeological excavation"
    agent.store.setze_entwurfsdaten(post_id, draft)
    agent.store.setze_karussell(post_id, ["/a.png"])
    fund = _schwach(titel="409 Goldrubel in Torschok", bildsuche="Torzhok gold hoard")
    agent.store.set_fund(post_id, fund)

    themen = []
    monkeypatch.setattr(agent, "_blick_auf", lambda thema: themen.append(thema))
    monkeypatch.setattr(echtbild, "finde_und_hole", lambda *a, **k: None)

    agent.karte_neu(post_id, 2)

    assert themen and "Torschok" in themen[0]
    assert themen[0] != "archaeological excavation"


def test_beim_nachbessern_bleiben_die_suchbegriffe_der_karten():
    """Das Modell sieht nur die Texte - die Bildfelder kommen von der alten Karte."""
    alt = _mit_karten(2)
    for karte in alt.karten:
        karte.bildsuche = "Torzhok gold hoard"
        karte.bildwunsch = "gold coins in dark soil"
    antwort = _mit_karten(2)
    antwort.karten[1].text = "Versteckt unter dem Fundament"
    antwort.karten[1].akzentwort = "Fundament"

    neu = ueberarbeite_beitrag(
        _Brain(antwort), identity=_identitaet(), strategy=None, draft=alt, bericht=_bericht()
    )

    assert [k.bildsuche for k in neu.karten] == ["Torzhok gold hoard"] * 2
    assert neu.karten[1].bildwunsch == "gold coins in dark soil"
    assert neu.karten[1].text == "Versteckt unter dem Fundament"
    assert neu.karten[1].akzentwort == "Fundament"
