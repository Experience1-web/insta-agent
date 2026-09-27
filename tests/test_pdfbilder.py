"""Die Aufnahmen einer Studie aus ihrem PDF.

Die Korallenstudie speichert ihre Fotos so, wie Druckereien es tun: als
CMYK, komprimiert mit dem Verfahren von PNG. Die PDFs hier sind genau so
gebaut - von Hand, weil kein Programm sie zufaellig so schreibt.
"""

from __future__ import annotations

import io
import random
import zlib

from PIL import Image

from insta_agent.imaging.pdfbilder import MINDESTKANTE, bilder_aus_pdf


def _pixel(breite: int, hoehe: int, kanaele: int, seed: int = 1) -> bytes:
    zufall = random.Random(seed)
    zeile = bytes(zufall.randint(0, 255) for _ in range(breite * kanaele))
    return zeile * hoehe


def _png_zeilen(breite: int, hoehe: int, kanaele: int, roh: bytes) -> bytes:
    """Wie ein PNG seine Zeilen ablegt: je Zeile ein Filterbyte davor."""
    schritt = breite * kanaele
    return b"".join(b"\x00" + roh[i * schritt : (i + 1) * schritt] for i in range(hoehe))


def _pdf(*bilder: tuple[int, int, str, bytes, bool]) -> bytes:
    """Baut ein PDF mit Bildobjekten: (Breite, Hoehe, Farbraum, Daten, Predictor)."""
    teile = [b"%PDF-1.7\n"]
    for nummer, (breite, hoehe, raum, daten, predictor) in enumerate(bilder, start=10):
        kanaele = {"/DeviceRGB": 3, "/DeviceCMYK": 4, "/DeviceGray": 1}[raum]
        parms = (
            f"/DecodeParms << /Predictor 15 /Colors {kanaele} /Columns {breite} >>"
            if predictor
            else ""
        )
        kopf = (
            f"{nummer} 0 obj\n<< /Type /XObject /Subtype /Image /Width {breite} "
            f"/Height {hoehe} /ColorSpace {raum} /BitsPerComponent 8 "
            f"/Filter /FlateDecode {parms} /Length {len(daten)} >>\nstream\n"
        ).encode()
        teile.append(kopf + daten + b"\nendstream\nendobj\n")
    teile.append(b"%%EOF\n")
    return b"".join(teile)


def test_rgb_mit_predictor_wird_gelesen(tmp_path):
    roh = _pixel(1200, 900, 3)
    daten = zlib.compress(_png_zeilen(1200, 900, 3, roh))
    pfade = bilder_aus_pdf(_pdf((1200, 900, "/DeviceRGB", daten, True)), tmp_path, "s")

    assert len(pfade) == 1
    with Image.open(pfade[0]) as bild:
        assert bild.size == (1200, 900)
        assert bild.mode == "RGB"


def test_cmyk_mit_predictor_wird_nach_rgb_umgerechnet(tmp_path):
    """So speichert die Korallenstudie ihre Fotos."""
    roh = _pixel(1000, 1000, 4)
    daten = zlib.compress(_png_zeilen(1000, 1000, 4, roh))
    pfade = bilder_aus_pdf(_pdf((1000, 1000, "/DeviceCMYK", daten, True)), tmp_path, "s")

    assert len(pfade) == 1
    with Image.open(pfade[0]) as bild:
        assert bild.mode == "RGB"


def test_ohne_predictor_wird_auch_gelesen(tmp_path):
    roh = _pixel(1000, 800, 3)
    pfade = bilder_aus_pdf(
        _pdf((1000, 800, "/DeviceRGB", zlib.compress(roh), False)), tmp_path, "s"
    )
    assert len(pfade) == 1


def test_jpeg_im_pdf_wird_gelesen(tmp_path):
    """So schreibt Pillow selbst Fotos in ein PDF."""
    zufall = random.Random(3)
    klein = Image.new("RGB", (40, 30))
    klein.putdata([tuple(zufall.randint(0, 255) for _ in range(3)) for _ in range(1200)])
    puffer = io.BytesIO()
    klein.resize((1600, 1200)).save(puffer, "PDF")

    pfade = bilder_aus_pdf(puffer.getvalue(), tmp_path, "s")
    assert len(pfade) == 1
    with Image.open(pfade[0]) as bild:
        assert bild.size == (1600, 1200)


def test_kleine_bilder_fallen_raus(tmp_path):
    """Logos, Symbole, Vorschaubildchen - kein Material fuer einen Beitrag."""
    klein = MINDESTKANTE - 100
    roh = _pixel(klein, 200, 3)
    daten = zlib.compress(_png_zeilen(klein, 200, 3, roh))
    assert bilder_aus_pdf(_pdf((klein, 200, "/DeviceRGB", daten, True)), tmp_path, "s") == []


def test_das_groesste_bild_kommt_zuerst(tmp_path):
    a = zlib.compress(_png_zeilen(1000, 900, 3, _pixel(1000, 900, 3)))
    b = zlib.compress(_png_zeilen(2000, 1500, 3, _pixel(2000, 1500, 3, seed=2)))
    pfade = bilder_aus_pdf(
        _pdf((1000, 900, "/DeviceRGB", a, True), (2000, 1500, "/DeviceRGB", b, True)),
        tmp_path,
        "s",
    )
    with Image.open(pfade[0]) as erstes:
        assert erstes.size == (2000, 1500)


def test_kaputte_bilder_kosten_nicht_das_ganze_pdf(tmp_path):
    gut = zlib.compress(_png_zeilen(1000, 900, 3, _pixel(1000, 900, 3)))
    kaputt = b"das ist kein zlib"
    pfade = bilder_aus_pdf(
        _pdf((1000, 900, "/DeviceRGB", kaputt, True), (1000, 900, "/DeviceRGB", gut, True)),
        tmp_path,
        "s",
    )
    assert len(pfade) == 1


def test_kein_pdf_ergibt_nichts(tmp_path):
    assert bilder_aus_pdf(b"<html>Fehlerseite</html>", tmp_path, "s") == []
