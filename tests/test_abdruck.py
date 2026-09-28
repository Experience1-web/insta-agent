"""'Bild neu' bringt ein anderes Bild, nicht dasselbe noch einmal."""

from __future__ import annotations

import json

from PIL import Image, ImageDraw, ImageEnhance

from insta_agent.imaging.abdruck import abdruck, abstand, schon_verwendet
from test_cycle import agent, settings  # noqa: F401 - Fixtures


def _motiv(pfad, form: str, groesse=(800, 1000)):
    bild = Image.new("RGB", groesse, (30, 40, 60))
    zeichnen = ImageDraw.Draw(bild)
    w, h = groesse
    if form == "kreis":
        zeichnen.ellipse((w * 0.2, h * 0.3, w * 0.8, h * 0.7), fill=(220, 200, 90))
    else:
        zeichnen.rectangle((0, 0, w * 0.4, h), fill=(200, 60, 40))
        zeichnen.rectangle((w * 0.6, h * 0.5, w, h), fill=(40, 200, 120))
    bild.save(pfad)
    return pfad


def test_dasselbe_foto_wird_erkannt_auch_verkleinert_und_umgefaerbt(tmp_path):
    original = _motiv(tmp_path / "a.jpg", "kreis")
    Image.open(original).resize((300, 375)).save(tmp_path / "klein.jpg")
    ImageEnhance.Brightness(Image.open(original)).enhance(1.2).save(tmp_path / "hell.jpg")
    anderes = _motiv(tmp_path / "b.jpg", "streifen")

    bekannt = [abdruck(original)]

    assert schon_verwendet(tmp_path / "klein.jpg", bekannt)
    assert schon_verwendet(tmp_path / "hell.jpg", bekannt)
    assert not schon_verwendet(anderes, bekannt)
    assert abstand(abdruck(original), abdruck(anderes)) > 10


def test_unlesbares_gilt_nicht_als_verwendet(tmp_path):
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"kein bild")
    assert abdruck(kaputt) is None
    assert not schon_verwendet(kaputt, [123])


def test_der_blick_wirft_verwendete_bilder_raus_bevor_er_fragt(agent, tmp_path):
    alt = _motiv(tmp_path / "alt.jpg", "kreis")
    neu = _motiv(tmp_path / "neu.jpg", "streifen")
    gefragt = []
    agent.brain.beurteile_bild = lambda pfad, thema, herkunft="": (gefragt.append(pfad), (9, "passt"))[1]
    agent.settings.posting.bilder_ansehen = True
    agent._ausschluss = [abdruck(alt)]

    blick = agent._blick_auf("Goldschatz")

    assert blick(alt)[0] == 0
    assert gefragt == []  # kostet nichts
    assert blick(neu) == (9, "passt")


def test_bild_neu_schliesst_das_jetzige_bild_aus(agent, tmp_path, monkeypatch):
    from test_stoff import _schwach

    agent.run_cycle()
    post = agent.store.pending_drafts()[0]
    jetzt = _motiv(tmp_path / "jetzt.jpg", "kreis")
    agent.store.setze_rohbild(post["id"], str(jetzt))
    agent.store.set_fund(post["id"], _schwach(titel="Goldschatz"))

    gesehen = {}

    def probe(fund, report):
        gesehen["ausschluss"] = list(agent._ausschluss)
        from insta_agent.runner import Bildprobe

        agent._bildproben = {id(fund): Bildprobe(None, "", [], "Goldschatz", None)}
        return False

    monkeypatch.setattr(agent, "_bildprobe", probe)
    agent.bild_neu(post["id"])

    assert abdruck(jetzt) in gesehen["ausschluss"]


def test_die_abdruecke_eines_beitrags_werden_gesammelt(agent, tmp_path):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    a = _motiv(tmp_path / "a.jpg", "kreis")
    b = _motiv(tmp_path / "b.jpg", "streifen")

    agent._merke_fuer_beitrag(b)
    agent._merke_abdruecke(post_id, a)

    gespeichert = agent.store.get_json(f"abdruecke:{post_id}")
    assert abdruck(a) in gespeichert and abdruck(b) in gespeichert
    assert json.dumps(gespeichert)  # als JSON speicherbar
