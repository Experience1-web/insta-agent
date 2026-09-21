"""Ob ein Bild im Beitrag scharf ankommt - und ob das Format daran schuld ist.

Die Bilder hier sind gerechnet, nicht fotografiert. Das reicht, weil es
nicht um Motive geht, sondern um eine Eigenschaft, die sich herstellen
laesst: Ein weichgezeichnetes Bild ist nachweislich unschaerfer als
dasselbe ohne, und ein hochgerechnetes nachweislich unschaerfer als
eines, das schon gross war.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageFilter

from insta_agent.imaging.schaerfe import SCHARF_GENUG, ist_scharf, schaerfewert

FEED = (1080, 1350)


def naturbild(breite: int, hoehe: int, seed: int = 1) -> Image.Image:
    """Mehrere Rauschlagen uebereinander - statistisch wie eine Aufnahme.

    Ein reines Zufallsbild waere unbrauchbar: Es hat ueberall gleich
    viel Energie und ist damit weder scharf noch unscharf im Sinne
    dieser Messung. Eine Fotografie hat viel Struktur im Groben und
    wenig im Feinen, und genau das bilden die Lagen nach.
    """
    random.seed(seed)
    gesamt = Image.new("L", (breite, hoehe), 0)
    for stufe, gewicht in ((4, 110), (16, 70), (64, 45), (256, 28), (breite, 18)):
        klein = Image.new("L", (max(2, stufe), max(2, int(stufe * hoehe / breite))))
        klein.putdata(
            [random.randint(0, 255) for _ in range(klein.width * klein.height)]
        )
        gesamt = Image.blend(gesamt, klein.resize((breite, hoehe), Image.BICUBIC), gewicht / 255)
    return gesamt.convert("RGB")


def lege_ab(bild: Image.Image, pfad):
    bild.save(pfad)
    return pfad


def test_scharfes_bild_besteht(tmp_path):
    pfad = lege_ab(naturbild(*FEED), tmp_path / "scharf.png")
    taugt, grund = ist_scharf(pfad, groesse=FEED)
    assert taugt, grund


def test_weichgezeichnetes_bild_faellt_durch(tmp_path):
    """Der Fall aus dem Betrieb: gross genug, trotzdem weich."""
    weich = naturbild(*FEED).filter(ImageFilter.GaussianBlur(1.5))
    pfad = lege_ab(weich, tmp_path / "weich.png")
    taugt, grund = ist_scharf(pfad, groesse=FEED)
    assert not taugt
    assert "unscharf" in grund


def test_hochgerechnetes_bild_faellt_durch(tmp_path):
    """Auf das Doppelte hochgerechnet - genau das, was ein falsches
    Zielformat mit einer Aufnahme macht."""
    klein = naturbild(540, 675)
    pfad = lege_ab(klein.resize(FEED, Image.LANCZOS), tmp_path / "gross.png")
    assert not ist_scharf(pfad, groesse=FEED)[0]


def test_verkleinertes_bild_besteht(tmp_path):
    """Heruntergerechnet wird ein Bild eher schaerfer, nie unschaerfer."""
    pfad = lege_ab(naturbild(2160, 2700), tmp_path / "gross.png")
    assert ist_scharf(pfad, groesse=FEED)[0]


def test_offene_blende_besteht_wegen_des_scharfen_motivs(tmp_path):
    """Ein Foto mit weichem Hintergrund ist ein gutes Foto, kein schlechtes.

    Ueber das ganze Bild gemittelt faellt es durch. Deshalb wird in
    Kacheln gemessen und die beste genommen - scharf sein muss das
    Motiv, nicht die Flaeche dahinter.
    """
    scharf = naturbild(*FEED, seed=2)
    weich = scharf.filter(ImageFilter.GaussianBlur(4))
    maske = Image.new("L", FEED, 0)
    ImageDraw.Draw(maske).ellipse((300, 420, 780, 930), fill=255)
    maske = maske.filter(ImageFilter.GaussianBlur(60))
    pfad = lege_ab(Image.composite(scharf, weich, maske), tmp_path / "bokeh.png")

    assert ist_scharf(pfad, groesse=FEED)[0]


def test_kontrastarmes_bild_gilt_nicht_als_unscharf(tmp_path):
    """Nebel, Nachthimmel, Tiefsee: wenig Kontrast, aber scharf.

    Ein absolutes Mass haette die verworfen - dieser Fehler ist bei der
    Frage, ob etwas ein Foto ist, schon dreimal passiert. Die Kennzahl
    ist ein Verhaeltnis, damit sich der Motivkontrast herauskuerzt.
    """
    flau = Image.eval(naturbild(*FEED, seed=3), lambda w: 110 + (w - 128) // 6)
    pfad = lege_ab(flau, tmp_path / "flau.png")
    assert ist_scharf(pfad, groesse=FEED)[0]


def test_leere_flaeche_wird_nicht_verworfen(tmp_path):
    """An einer einfarbigen Flaeche ist nichts zu messen.

    Keine Messung ist kein Grund zu verwerfen - sonst faellt ein Bild
    durch, ueber das die Pruefung gar nichts weiss.
    """
    pfad = lege_ab(Image.new("RGB", FEED, (30, 30, 30)), tmp_path / "leer.png")
    assert schaerfewert(pfad, groesse=FEED) == 0.0
    assert ist_scharf(pfad, groesse=FEED)[0]


def test_fehlende_datei_gilt_als_scharf(tmp_path):
    """Ein Fehler beim Messen darf kein Bild kosten."""
    assert ist_scharf(tmp_path / "gibtsnicht.png")[0]


def test_die_schwelle_liegt_zwischen_den_beiden_lagern(tmp_path):
    """Damit die Zahl nicht unbemerkt in die falsche Gegend wandert."""
    scharf = schaerfewert(lege_ab(naturbild(*FEED), tmp_path / "a.png"), groesse=FEED)
    weich = schaerfewert(
        lege_ab(
            naturbild(*FEED).filter(ImageFilter.GaussianBlur(1.5)), tmp_path / "b.png"
        ),
        groesse=FEED,
    )
    assert weich < SCHARF_GENUG < scharf


def test_das_falsche_zielformat_kostet_messbar_schaerfe(tmp_path):
    """Dieselbe Aufnahme, zwei Formate - und ein Unterschied, den man sieht.

    Eine Querformataufnahme von 2400 x 1565 wird fuer den Feed (4:5) auf
    das 0,86-fache verkleinert und fuer eine Story (9:16) auf das
    1,23-fache hochgerechnet. Genau das ist jahrelang unbemerkt passiert,
    weil das eingestellte Format beim Beschriften nie gelesen wurde.

    Die Schaerfemessung faengt diesen Fall nicht allein - 1,23 liegt
    knapp ueber der Schwelle, und sie tiefer zu legen hiesse, brauchbare
    Bilder zu verwerfen. Dafuer gibt es die Massprobe in der Bildsuche.
    Messbar ist der Unterschied trotzdem, und das muss so bleiben.
    """
    pfad = lege_ab(naturbild(2400, 1565), tmp_path / "quer.png")
    im_feed = schaerfewert(pfad, groesse=(1080, 1350))
    in_story = schaerfewert(pfad, groesse=(1080, 1920))
    assert in_story < im_feed
    assert im_feed > SCHARF_GENUG
