"""Der feste Rahmen: Etikett, Seitenzähler, Wisch-Hinweis, Abschlusskarte."""

from __future__ import annotations

import json
from types import SimpleNamespace

from PIL import Image

from insta_agent.imaging.marke import (
    Marke,
    etikett_fuer,
    frage_aus,
    quelle_aus,
    render_abschlusskarte,
)
from insta_agent.models import VisualSpec


def test_das_etikett_kommt_aus_der_themensaeule():
    assert etikett_fuer("Lebendig") == "NATUR"
    assert etikett_fuer("Ausgegraben: Tempel, Gräber") == "ARCHÄOLOGIE"
    # "Erfunden" klänge auf einem Faktenaccount nach "ausgedacht".
    assert etikett_fuer("Erfunden") == "FORSCHUNG"
    assert etikett_fuer("") == ""


def test_die_quelle_kommt_aus_der_letzten_quellenzeile():
    caption = "Ein Fund.\n\n📚 Quelle: Nature, November 2026"
    assert quelle_aus(caption) == "Nature, November 2026"
    assert quelle_aus("Ohne Beleg.") == ""


def test_die_frage_ohne_den_aufruf_davor():
    assert frage_aus("Speicher das - und sag uns: Wie viele sind es?") == "Wie viele sind es?"
    assert frage_aus("Speichere das.", "Welches Tier hättest du erwartet?") == (
        "Welches Tier hättest du erwartet?"
    )
    # Ein Gedankenstrich mitten in der Frage gehört zur Frage.
    assert frage_aus("Welches Tier kanntest du – und wusstest es nicht?") == (
        "Welches Tier kanntest du – und wusstest es nicht?"
    )


def test_die_abschlusskarte_wird_gezeichnet(tmp_path):
    ziel = render_abschlusskarte(
        VisualSpec(headline="x", accent_hex="#3FA9A3"),
        tmp_path / "ende.png",
        frage="Was hättest du gedacht?",
        quelle="Nature, November 2026",
        handle="@probe",
        marke=Marke(etikett="NATUR", seite="5/5"),
    )
    assert Image.open(ziel).size == (1080, 1350)


def test_der_rahmen_landet_auf_dem_foto(tmp_path):
    from insta_agent.imaging import FEED, lege_hook_auf

    roh = tmp_path / "roh.png"
    Image.new("RGB", FEED, (20, 20, 20)).save(roh)
    spec = VisualSpec(headline="x", accent_hex="#7BE05A")
    ohne = Image.open(lege_hook_auf(roh, tmp_path / "a.png", text="Satz", spec=spec, groesse=FEED))
    mit = Image.open(
        lege_hook_auf(
            roh, tmp_path / "b.png", text="Satz", spec=spec, groesse=FEED,
            marke=Marke(etikett="NATUR", seite="2/5", wischen=True),
        )
    )
    # Oben links steht jetzt etwas, wo vorher nur Grund war.
    assert ohne.crop((80, 60, 300, 100)).getextrema() != mit.crop((80, 60, 300, 100)).getextrema()


def _agent_mit_beitrag(tmp_path, karussell: list[str]):
    from insta_agent.runner import Agent

    agent = object.__new__(Agent)
    agent.settings = SimpleNamespace(media_dir=tmp_path)
    agent.store = SimpleNamespace(get_json=lambda k: None, get_model=lambda k, m: None)
    entwurf = {
        "pillar": "Lebendig",
        "hook_text_on_screen": "Ein Fund",
        "image_generation_prompt": "",
        "hook": "",
        "caption": "Ein Fund.\n\n📚 Quelle: Nature, 2026",
        "body_text": "",
        "call_to_action": "Was meinst du?",
        "hashtags": [],
        "first_comment_prompt": "",
        "visual": {"headline": "Ein Fund", "footer": "@probe"},
        "best_time_hint": "",
        "expected_outcome": "",
    }
    zeile = {"id": 7, "karussell_json": json.dumps(karussell), "draft_json": json.dumps(entwurf)}
    return agent, zeile


def test_ohne_karussell_keine_abschlusskarte(tmp_path):
    agent, zeile = _agent_mit_beitrag(tmp_path, [])
    assert agent.abschlusskarte(zeile) is None


def test_die_abschlusskarte_wird_nur_bei_aenderung_neu_geschrieben(tmp_path):
    """Sonst wäre sie bei jedem Blick ins Dashboard neuer als das Reel."""
    import os

    agent, zeile = _agent_mit_beitrag(tmp_path, [str(tmp_path / "k2.png")])
    erste = agent.abschlusskarte(zeile)
    assert erste is not None and erste.is_file()
    os.utime(erste, (1, 1))

    zweite = agent.abschlusskarte(zeile)
    assert zweite == erste
    assert erste.stat().st_mtime == 1
