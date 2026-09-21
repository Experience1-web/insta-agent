"""Mehrere Bilder in einem Beitrag, durch die man wischt.

Der Grund ist nicht die Menge, sondern die Bewegung: Wer wischt, bleibt,
und wer bleibt, zaehlt bei Instagram mehr als zehn, die vorbeiziehen.

Zwei Dinge duerfen dabei nicht schiefgehen. Die Bilder muessen
zusammenpassen - fuenf Bilder aus fuenf Welten sind ein Sammelsurium.
Und ein Karussell, das nicht zustande kommt, darf den Beitrag nicht
mitnehmen: Das erste Bild traegt ihn auch allein.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from PIL import Image

from insta_agent.models import Karte


def _bild(pfad: Path, farbe: tuple[int, int, int], groesse=(400, 500)) -> Path:
    Image.new("RGB", groesse, farbe).save(pfad)
    return pfad


def _mittelfarbe(pfad: Path) -> tuple[int, int, int]:
    with Image.open(pfad) as bild:
        return bild.convert("RGB").resize((1, 1), Image.LANCZOS).getpixel((0, 0))[:3]


# --- Die Karten selbst ------------------------------------------------------


def test_eine_karte_traegt_eine_tatsache():
    karte = Karte(text="59,35 Lichtjahre entfernt", akzentwort="59,35")
    assert karte.text
    # Bildwunsch und Bildsuche sind freiwillig: Von einem Exoplaneten
    # gibt es kein Foto, von einem Muenzhort schon.
    assert karte.bildwunsch == ""
    assert karte.bildsuche == ""


def test_ein_entwurf_ohne_karten_ist_voellig_in_ordnung(draft):
    """Ein starkes Bild schlaegt fuenf, von denen drei nichts sagen.

    Die Zahl richtet sich am Ereignis aus, nicht an einer Regel - also
    muss null genauso gueltig sein wie vier.
    """
    assert draft.karten == []


# --- Angleichen -------------------------------------------------------------


def test_verschiedene_aufnahmen_ruecken_farblich_zusammen(tmp_path):
    """Sonst steht eine kuehle Teleskopaufnahme neben einer warmen Grabung.

    Bei gemalten Bildern regelt das der Prompt. Bei echten Aufnahmen aus
    einem Archiv geht das nicht - die sind, wie sie sind. Also wird
    nachgearbeitet.
    """
    from insta_agent.imaging.angleichen import gleiche_an

    kalt = _bild(tmp_path / "kalt.png", (40, 90, 160))
    warm = _bild(tmp_path / "warm.png", (170, 120, 60))
    vorher = math.dist(_mittelfarbe(kalt), _mittelfarbe(warm))

    for pfad in (kalt, warm):
        assert gleiche_an(pfad, hintergrund_hex="#0B1220", akzent_hex="#E4572E")

    nachher = math.dist(_mittelfarbe(kalt), _mittelfarbe(warm))
    assert nachher < vorher, "Die Bilder sind einander nicht naehergekommen"
    # Aber sie bleiben zwei Bilder. Ein durchgefaerbtes Foto sieht aus
    # wie ein Filter, und ein Filter sieht billig aus.
    assert nachher > 40, "Das sieht nach Filter aus, nicht nach Handschrift"


def test_ein_kaputtes_bild_bleibt_einfach_liegen(tmp_path):
    """Unbearbeitet ist besser als gar nicht."""
    from insta_agent.imaging.angleichen import gleiche_an

    kaputt = tmp_path / "kaputt.png"
    kaputt.write_bytes(b"das ist kein Bild")
    assert gleiche_an(kaputt, hintergrund_hex="#000000", akzent_hex="#ffffff") is False
    assert kaputt.read_bytes() == b"das ist kein Bild"


def test_das_angleichen_erhaelt_die_zeichnung(tmp_path):
    """Ein Bild ohne Zeichnung waere eine Farbflaeche, kein Foto."""
    from insta_agent.imaging.angleichen import gleiche_an

    pfad = tmp_path / "verlauf.png"
    bild = Image.new("RGB", (256, 64))
    for x in range(256):
        for y in range(64):
            bild.putpixel((x, y), (x, x, x))
    bild.save(pfad)

    gleiche_an(pfad, hintergrund_hex="#0B1220", akzent_hex="#E4572E")

    with Image.open(pfad) as danach:
        grau = danach.convert("L")
        assert grau.getpixel((250, 32)) - grau.getpixel((5, 32)) > 150


# --- Veroeffentlichen -------------------------------------------------------


class _Api:
    """Ein Instagram, das mitschreibt statt zu veroeffentlichen."""

    def __init__(self, *, kinder_scheitern: bool = False) -> None:
        self.kinder: list[str] = []
        self.eltern: list[tuple[list[str], str]] = []
        self.einzeln: list[str] = []
        self.kinder_scheitern = kinder_scheitern

    def create_carousel_item(self, image_url: str) -> str:
        from insta_agent.instagram.client import GraphAPIError

        if self.kinder_scheitern:
            raise GraphAPIError("Bild abgelehnt")
        self.kinder.append(image_url)
        return f"kind-{len(self.kinder)}"

    def create_carousel(self, children: list[str], caption: str) -> str:
        self.eltern.append((list(children), caption))
        return "eltern-1"

    def create_container(self, image_url: str, caption: str) -> str:
        self.einzeln.append(image_url)
        return "einzeln-1"

    def wait_until_ready(self, container_id: str) -> None:
        return None

    def publish_container(self, container_id: str) -> str:
        return f"ig-{container_id}"


def _verlag(api, tmp_path):
    """Ein Verlag, dessen Bildordner wirklich existiert.

    Ohne das findet er keine oeffentliche Adresse - Instagram laedt keine
    Dateien hoch, es holt sie von einer URL, und die gibt es nur fuer
    Bilder aus dem veroeffentlichten Ordner.
    """
    from insta_agent.instagram.publisher import Publisher

    (tmp_path / "media").mkdir(exist_ok=True)
    return Publisher(
        client=api,
        draft_dir=tmp_path / "drafts",
        media_dir=tmp_path / "media",
        live=True,
        public_base_url="https://example.test/bilder",
    )


def test_mehrere_bilder_gehen_als_karussell_hinaus(draft, tmp_path):
    """Jedes Bild einzeln hochladen, dann als Gruppe - so will es Instagram."""
    api = _Api()
    verlag = _verlag(api, tmp_path)

    medien = tmp_path / "media"
    erstes = _bild(medien / "1.png", (10, 10, 10))
    weitere = [_bild(medien / f"{i}.png", (20 * i, 20, 20)) for i in (2, 3)]

    ergebnis = verlag.publish(draft, erstes, "", weitere=weitere)

    assert ergebnis.published
    assert len(api.kinder) == 3, "Alle drei Bilder muessen einzeln hoch"
    assert len(api.eltern) == 1
    kinder, caption = api.eltern[0]
    assert kinder == ["kind-1", "kind-2", "kind-3"], "Die Reihenfolge zaehlt"
    # Die Bildunterschrift steht am Elternteil, nicht an jedem Bild.
    assert draft.caption.strip()[:20] in caption
    assert not api.einzeln


def test_ein_gescheitertes_karussell_nimmt_den_beitrag_nicht_mit(draft, tmp_path):
    """Das erste Bild traegt den Beitrag auch allein.

    Der teuerste denkbare Fehler waere, einen fertig geprueften Beitrag
    wegzuwerfen, weil ein Zusatzbild nicht durchkam.
    """
    api = _Api(kinder_scheitern=True)
    verlag = _verlag(api, tmp_path)

    medien = tmp_path / "media"
    erstes = _bild(medien / "1.png", (10, 10, 10))
    weitere = [_bild(medien / "2.png", (40, 20, 20))]

    ergebnis = verlag.publish(draft, erstes, "", weitere=weitere)

    assert ergebnis.published, "Der Beitrag haette einzeln hinausgehen muessen"
    assert api.einzeln, "Es wurde kein einzelner Versuch unternommen"
    assert not api.eltern


def test_ohne_weitere_bilder_bleibt_alles_wie_vorher(draft, tmp_path):
    api = _Api()
    verlag = _verlag(api, tmp_path)
    ergebnis = verlag.publish(draft, _bild(tmp_path / "media" / "1.png", (10, 10, 10)), "")

    assert ergebnis.published
    assert not api.kinder and not api.eltern
    assert len(api.einzeln) == 1


def test_ein_karussell_braucht_mindestens_zwei_bilder(tmp_path):
    """Instagram lehnt eines ab - der Fehler gehoert hierher, nicht dorthin."""
    from insta_agent.instagram.client import GraphAPIError

    api = _Api()
    with pytest.raises(GraphAPIError, match="2 und 10"):
        api_client = __import__(
            "insta_agent.instagram.client", fromlist=["InstagramClient"]
        ).InstagramClient
        api_client.create_carousel(api, ["nur-eines"], "Text")


# --- Speichern --------------------------------------------------------------


def test_die_reihenfolge_der_bilder_bleibt_erhalten(tmp_path):
    """Gewischt wird in einer Reihenfolge, und die ist nicht beliebig."""
    from insta_agent.store import Store

    store = Store(tmp_path / "s.db")
    try:

        class Entwurf:
            pillar = "Weltall"
            caption = "Text"
            hashtags: list[str] = []

            def model_dump(self, mode=None):
                return {"caption": "Text", "hashtags": []}

        post_id = store.add_draft(Entwurf(), "erstes.png")
        assert store.get_post(post_id)["karussell_json"] is None

        store.setze_karussell(post_id, ["a.png", "b.png", "c.png"])
        import json

        assert json.loads(store.get_post(post_id)["karussell_json"]) == [
            "a.png",
            "b.png",
            "c.png",
        ]

        # Leer heisst wieder leer, nicht "[]".
        store.setze_karussell(post_id, [])
        assert store.get_post(post_id)["karussell_json"] is None
    finally:
        store.close()


# --- Panorama ---------------------------------------------------------------


def _verlauf(pfad: Path, breite: int, hoehe: int) -> Path:
    """Ein lueckenloser waagerechter Verlauf - damit sieht man jede Naht."""
    zeile = Image.new("RGB", (breite, 1))
    px = zeile.load()
    for x in range(breite):
        anteil = int(255 * x / max(1, breite - 1))
        px[x, 0] = (anteil, 80, 255 - anteil)
    zeile.resize((breite, hoehe), Image.NEAREST).save(pfad)
    return pfad


def test_die_stuecke_schliessen_nahtlos_aneinander(tmp_path):
    """Der ganze Sinn der Sache.

    Wer wischt, soll an einer Aufnahme entlangfahren. Eine Luecke oder
    eine Ueberlappung an der Naht sieht man sofort - und dann ist es
    wieder ein Stapel Kacheln.
    """
    from insta_agent.imaging.panorama import zerschneide

    quelle = _verlauf(tmp_path / "pano.png", 4800, 1600)
    teile = zerschneide(quelle, tmp_path / "pano", format_breite=864, format_hoehe=1080)

    assert len(teile) >= 3
    for links, rechts in zip(teile, teile[1:]):
        with Image.open(links) as a, Image.open(rechts) as b:
            kante_a = a.convert("RGB").getpixel((863, 540))
            kante_b = b.convert("RGB").getpixel((0, 540))
        sprung = sum(abs(x - y) for x, y in zip(kante_a, kante_b))
        assert sprung < 12, f"Sichtbarer Bruch an der Naht: {kante_a} | {kante_b}"


def test_ein_gewoehnliches_querformat_wird_nicht_zerschnitten(tmp_path):
    """Sonst bekommt man drei angeschnittene Bilder und kein Panorama."""
    from insta_agent.imaging.panorama import ist_panorama

    assert ist_panorama(_verlauf(tmp_path / "quer.png", 2000, 1300)) is False
    assert ist_panorama(_verlauf(tmp_path / "pano.png", 4800, 1600)) is True


def test_ein_zu_kleines_panorama_bleibt_ganz(tmp_path):
    """Hochgerechnete Stuecke sehen schlechter aus als ein ganzes Bild."""
    from insta_agent.imaging.panorama import zerschneide

    quelle = _verlauf(tmp_path / "klein.png", 1200, 400)
    assert zerschneide(quelle, tmp_path / "klein", format_breite=864, format_hoehe=1080) == []


def test_die_stuecke_sind_nicht_verzerrt(tmp_path):
    """Aufgerundet statt gerundet - sonst quetscht es das Bild.

    Die Breite eines Stuecks ist unverhandelbar, sonst klafft die Naht.
    Also muss die Hoehe nachgeben, und dafuer muss genug davon da sein.
    """
    from insta_agent.imaging.panorama import stueckzahl

    for breite, hoehe in ((4800, 1600), (6000, 1200), (3000, 1000), (2600, 1100)):
        zahl = stueckzahl(breite, hoehe, 864 / 1080)
        if not zahl:
            continue
        # Genauso rechnet `zerschneide`: Bei einem sehr langen Band wird
        # nur die Mitte genommen, statt die ganze Laenge zu quetschen.
        nutzbreite = min(breite, int(zahl * hoehe * (864 / 1080)))
        stueck = nutzbreite // zahl
        noetige_hoehe = stueck / (864 / 1080)
        assert noetige_hoehe <= hoehe + 1, (
            f"{breite}x{hoehe} in {zahl} Stuecke braucht {noetige_hoehe:.0f} "
            f"Pixel Hoehe, hat aber nur {hoehe}"
        )
