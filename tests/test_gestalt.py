"""Das Gestaltungssystem: Schriften, Rubrikfarben, Layouts, Satz."""

from __future__ import annotations

import random

from PIL import Image, ImageStat

from insta_agent.imaging import gestalt


def _foto(pfad, *, unruhig_oben: bool):
    """Ein Foto, das oben oder unten voller Details ist und auf der anderen Seite ruhig."""
    random.seed(3)
    bild = Image.new("RGB", (1080, 1350), (90, 110, 130))
    punkte = bild.load()
    bereich = range(0, 600) if unruhig_oben else range(750, 1350)
    for y in bereich:
        for x in range(0, 1080, 2):
            wert = random.randint(0, 255)
            punkte[x, y] = (wert, wert, wert)
    bild.save(pfad)
    return pfad


def test_die_eigenen_schriften_werden_geladen():
    assert gestalt.SERIFE.is_file() and gestalt.GROTESK.is_file()
    titel = gestalt.schrift("titel", 80)
    assert "Source Serif" in titel.getname()[0]
    assert "Inter" in gestalt.schrift("text", 30).getname()[0]


def test_jede_rubrik_hat_ihre_farbe():
    assert gestalt.akzent_fuer("NATUR") != gestalt.akzent_fuer("WELTALL")
    assert gestalt.akzent_fuer("gibt es nicht") == gestalt.STANDARDAKZENT


def test_deutsche_satzzeichen():
    assert gestalt.feinsatz("Foto - ein Verfahren") == "Foto – ein Verfahren"
    assert gestalt.feinsatz('Er sagte "Hallo"') == "Er sagte „Hallo“"
    # Ein Bindestrich im Wort bleibt einer.
    assert gestalt.feinsatz("Heard-Insel") == "Heard-Insel"


def test_der_titel_steht_dort_wo_das_bild_ruhig_ist(tmp_path):
    """Die Schrift soll das Motiv nicht verdecken."""
    unten_unruhig = _foto(tmp_path / "a.png", unruhig_oben=False)
    ziel = gestalt.titel(unten_unruhig, tmp_path / "t.png", ueberschrift="Ein ruhiger Satz oben",
                         rubrik="NATUR")
    bild = Image.open(ziel).convert("L")
    # Oben liegt jetzt helle Schrift auf dem abgedunkelten ruhigen Grund.
    oben = ImageStat.Stat(bild.crop((84, 150, 900, 260))).extrema[0][1]
    assert oben > 200


def test_auf_einer_fotokarte_bleibt_das_foto_frei(tmp_path):
    foto = _foto(tmp_path / "f.png", unruhig_oben=True)
    ziel = gestalt.karte_mit_foto(foto, tmp_path / "k.png", text="Ein Satz unter dem Bild",
                                  rubrik="WELTALL", seite="2/5")
    bild = Image.open(ziel).convert("RGB")
    # Unten ist der ruhige Grund mit der Schrift, nicht das Foto.
    unten = ImageStat.Stat(bild.crop((0, 1250, 1080, 1350))).mean
    assert all(abs(k - g) < 12 for k, g in zip(unten, gestalt.GRUND))


def test_ohne_foto_wird_eine_zahl_gross(tmp_path):
    ziel = gestalt.karte_ohne_foto(tmp_path / "z.png", text="Er ist 2.062 Meter hoch",
                                   rubrik="NATUR", seite="3/5")
    bild = Image.open(ziel).convert("RGB")
    gruen = sum(
        1 for p in bild.resize((270, 337)).getdata()
        if abs(p[0] - 140) < 25 and abs(p[1] - 192) < 25 and abs(p[2] - 132) < 25
    )
    assert gruen > 500


def test_die_abschlusskarte_kommt_ohne_frage_aus(tmp_path):
    """Nicht jede Geschichte braucht eine angehängte Frage."""
    ziel = gestalt.abschluss(tmp_path / "e.png", frage="", quelle="Nature, 2026",
                             handle="@probe", rubrik="KURIOS", seite="5/5")
    assert Image.open(ziel).size == (1080, 1350)
