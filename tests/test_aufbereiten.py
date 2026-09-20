"""Was Instagram annimmt - und was es mit einer unbrauchbaren Meldung ablehnt.

"Only photo or video can be accepted as media type" heisst in Wahrheit
fast immer: kein JPEG. Diese Pruefungen halten beide Bedingungen fest,
damit der Fehler nicht ein zweites Mal Stunden kostet.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from insta_agent.instagram.aufbereiten import (
    BREITESTE,
    SCHMALSTE,
    fuer_instagram,
)


def _bild(tmp_path, masse, modus="RGB", name="b.png"):
    pfad = tmp_path / name
    Image.new(modus, masse, (30, 40, 60) if modus == "RGB" else (30, 40, 60, 255)).save(pfad)
    return pfad


def _gelesen(daten: bytes) -> Image.Image:
    return Image.open(io.BytesIO(daten))


def test_aus_png_wird_jpeg(tmp_path):
    """Das ist die eigentliche Ursache von Fehler 9004."""
    ergebnis = _gelesen(fuer_instagram(_bild(tmp_path, (1080, 1350))))

    assert ergebnis.format == "JPEG"


def test_transparenz_bricht_nicht_ab(tmp_path):
    """JPEG kennt keinen Alphakanal - ein RGBA-Bild wuerde sonst scheitern."""
    daten = fuer_instagram(_bild(tmp_path, (1080, 1350), modus="RGBA"))

    assert _gelesen(daten).mode == "RGB"


@pytest.mark.parametrize(
    "masse",
    [(1080, 1920), (1080, 1350), (1920, 1080), (3000, 600), (1000, 1000), (800, 1000)],
)
def test_jedes_bild_landet_in_instagrams_rahmen(tmp_path, masse):
    ergebnis = _gelesen(fuer_instagram(_bild(tmp_path, masse)))
    verhaeltnis = ergebnis.width / ergebnis.height

    assert SCHMALSTE <= round(verhaeltnis, 3) <= BREITESTE, f"{masse} -> {ergebnis.size}"


def test_ein_passendes_bild_wird_nicht_angefasst(tmp_path):
    ergebnis = _gelesen(fuer_instagram(_bild(tmp_path, (1080, 1350))))

    assert ergebnis.size == (1080, 1350)


def test_beim_kuerzen_bleibt_der_hook_oben_stehen(tmp_path):
    """Der Hook ist der Grund, warum jemand stehenbleibt. Ihn abzuschneiden
    waere das Schlimmste, was man tun kann."""
    pfad = tmp_path / "hoch.png"
    bild = Image.new("RGB", (1080, 1920), (10, 10, 10))
    # Ein heller Streifen ganz oben - dort steht im echten Bild der Hook.
    for y in range(0, 300):
        for x in range(0, 1080, 4):
            bild.putpixel((x, y), (255, 255, 255))
    bild.save(pfad)

    ergebnis = _gelesen(fuer_instagram(pfad))

    assert ergebnis.size == (1080, 1350)
    # Der Streifen muss noch da sein.
    oben = ergebnis.crop((0, 0, 1080, 300)).convert("L").resize((1, 1)).getpixel((0, 0))
    assert oben > 60, "Der obere Bereich wurde weggeschnitten"


def test_die_datei_bleibt_klein_genug(tmp_path):
    """Instagram lehnt ab 8 MB ab."""
    daten = fuer_instagram(_bild(tmp_path, (1080, 1350)))

    assert len(daten) < 8 * 1024 * 1024


def test_das_oertliche_bild_bleibt_unveraendert(tmp_path):
    """Der Entwurf im Dashboard soll verlustfrei bleiben."""
    pfad = _bild(tmp_path, (1080, 1920))
    vorher = pfad.read_bytes()

    fuer_instagram(pfad)

    assert pfad.read_bytes() == vorher


def test_die_voreinstellung_passt_in_instagrams_rahmen():
    """9:16 ist fuer Reels. Im Feed wuerde es beschnitten."""
    from insta_agent.config import Settings
    from insta_agent.imaging.renderer import FEED

    assert Settings().posting.bildformat == "feed"
    assert SCHMALSTE <= FEED[0] / FEED[1] <= BREITESTE


def test_die_ablage_laedt_die_aufbereitete_fassung_hoch(tmp_path):
    """Sonst geht wieder ein PNG hinaus und Meta lehnt es ab."""
    import base64
    from urllib.parse import parse_qs

    import httpx

    from insta_agent.instagram.ablage import ImgbbAblage

    gesehen: dict[str, str] = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        gesehen.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"data": {"url": "https://i.test/a.jpg"}})

    a = ImgbbAblage("geheim")
    a.client = httpx.Client(transport=httpx.MockTransport(antworte))
    a.lade_hoch(_bild(tmp_path, (1080, 1920)))

    hochgeladen = _gelesen(base64.b64decode(gesehen["image"]))
    assert hochgeladen.format == "JPEG"
    assert hochgeladen.size == (1080, 1350)
