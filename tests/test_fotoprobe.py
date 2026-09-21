"""Ist das ein Foto - oder eine Zeichnung auf weissem Grund?

Die Bildsuche fand fuer "deep sea creature" eine Datei namens
"Humpback anglerfish.png". Lizenz frei, Groesse gut, Form gut, Platz
eins - und trotzdem falsch: eine wissenschaftliche Illustration,
freigestellt auf Weiss.

Fuer einen Account ueber tatsaechlich Geschehenes ist das schlimmer als
ein gemaltes Bild. Ein gemaltes gibt vor, eine Vorstellung zu sein. Eine
Strichzeichnung auf Weiss sieht im Feed aus wie ein Versehen.

Die Tests hier halten beide Richtungen fest - und die zweite ist die
wichtigere: Kein echtes Foto darf verworfen werden, schon gar keine
dunkle Tiefseeaufnahme.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from insta_agent.imaging.fotoprobe import wirkt_wie_foto


def _zeichnung(pfad: Path, grund=(255, 255, 255)) -> Path:
    bild = Image.new("RGB", (800, 760), grund)
    stift = ImageDraw.Draw(bild)
    stift.ellipse([250, 250, 550, 500], fill=(60, 60, 70), outline=(0, 0, 0), width=4)
    stift.polygon([(540, 375), (700, 300), (700, 450)], fill=(60, 60, 70))
    bild.save(pfad)
    return pfad


def _foto(pfad: Path, grund, spanne: int, unscharf: bool = False) -> Path:
    zufall = random.Random(7)
    bild = Image.new("RGB", (600, 750))
    punkte = bild.load()
    for y in range(750):
        for x in range(600):
            basis = grund(x, y)
            punkte[x, y] = tuple(
                max(0, min(255, k + zufall.randint(-spanne, spanne))) for k in basis
            )
    if unscharf:
        bild = bild.filter(ImageFilter.GaussianBlur(2))
    bild.save(pfad, quality=88)
    return pfad


# --- Was verworfen werden muss ---------------------------------------------


def test_eine_zeichnung_auf_weiss_ist_kein_foto(tmp_path):
    """Genau der Fall, der im Betrieb passiert ist."""
    taugt, grund = wirkt_wie_foto(_zeichnung(tmp_path / "fisch.png"))
    assert taugt is False
    assert "Zeichnung" in grund or "Grafik" in grund


def test_auch_auf_hellgrau_freigestellt_zaehlt(tmp_path):
    taugt, _ = wirkt_wie_foto(_zeichnung(tmp_path / "grau.png", (240, 240, 240)))
    assert taugt is False


def test_ein_diagramm_ist_kein_foto(tmp_path):
    pfad = tmp_path / "diagramm.png"
    bild = Image.new("RGB", (800, 600), (255, 255, 255))
    stift = ImageDraw.Draw(bild)
    for i in range(6):
        stift.rectangle([80 + i * 110, 500 - i * 60, 160 + i * 110, 520], fill=(40, 90, 160))
    bild.save(pfad)
    assert wirkt_wie_foto(pfad)[0] is False


def test_eine_flaeche_ohne_struktur_ist_kein_foto(tmp_path):
    """Die letzte Reserve, fuer Grafiken auf farbigem Grund."""
    pfad = tmp_path / "flaeche.png"
    Image.new("RGB", (600, 750), (40, 90, 160)).save(pfad)
    taugt, grund = wirkt_wie_foto(pfad)
    assert taugt is False
    assert "Struktur" in grund


# --- Was durchgehen muss ---------------------------------------------------
#
# Diese Haelfte ist die wichtigere. Ein Foto faelschlich zu verwerfen ist
# teurer, als eine Zeichnung durchzulassen: Dann wird gemalt, und ein
# gemaltes Bild ist immer die zweitbeste Loesung.


def test_eine_dunkle_tiefseeaufnahme_geht_durch(tmp_path):
    """Der teuerste Fehler, den diese Pruefung machen koennte.

    Eine erste Fassung zaehlte Farbtoene. Eine fast schwarze Aufnahme
    hat in groben Stufen kaum mehr davon als eine Strichzeichnung - und
    flog raus. Genau solche Aufnahmen sind fuer diesen Account die
    wertvollsten.
    """
    pfad = _foto(tmp_path / "tiefsee.jpg", lambda x, y: (6, 10, 18), 10)
    taugt, grund = wirkt_wie_foto(pfad)
    assert taugt is True, grund


def test_ein_nachthimmel_geht_durch(tmp_path):
    pfad = _foto(tmp_path / "nacht.jpg", lambda x, y: (3, 4, 9), 5)
    assert wirkt_wie_foto(pfad)[0] is True


def test_eine_schneelandschaft_geht_durch(tmp_path):
    """Hell und farbarm - und trotzdem eine Fotografie."""
    pfad = _foto(
        tmp_path / "schnee.jpg", lambda x, y: (190 + int(30 * y / 750), 195, 205), 14
    )
    taugt, grund = wirkt_wie_foto(pfad)
    assert taugt is True, grund


def test_eine_stark_unscharfe_aufnahme_geht_durch(tmp_path):
    """Die Schwelle, die dreimal falsch stand.

    Eine weichgezeichnete Fotografie kommt auf 0,2 bis 0,3 Struktur -
    mehr nicht. Wer die Schwelle darueber legt, verwirft Nebel, Rauch
    und jede Aufnahme mit offener Blende.
    """
    pfad = _foto(tmp_path / "nebel.jpg", lambda x, y: (150, 155, 160), 12, unscharf=True)
    taugt, grund = wirkt_wie_foto(pfad)
    assert taugt is True, grund


def test_ein_gewoehnliches_foto_geht_durch(tmp_path):
    pfad = _foto(
        tmp_path / "normal.jpg",
        lambda x, y: (20 + int(40 * y / 750), 40 + int(60 * y / 750), 70 + int(50 * x / 600)),
        18,
    )
    assert wirkt_wie_foto(pfad)[0] is True


def test_eine_kaputte_datei_wird_durchgelassen(tmp_path):
    """Im Zweifel ja - sonst verwirft ein Lesefehler ein gutes Bild."""
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"kein Bild")
    assert wirkt_wie_foto(kaputt)[0] is True
