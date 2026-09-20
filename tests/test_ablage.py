"""Der öffentliche Platz für die Bilder.

Wichtig ist auch hier der Fehlschlag: Wenn das Ablegen nicht klappt,
darf der Beitrag nicht verlorengehen - er bleibt freigegeben und wird
beim nächsten Zyklus erneut versucht.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from insta_agent.instagram.ablage import (
    HALTBARKEIT_SEKUNDEN,
    OHNE_SCHLUESSEL,
    Ablagefehler,
    ImgbbAblage,
    _lesbar,
    baue_ablage,
)
from insta_agent.instagram.aufbereiten import fuer_instagram


def _bild(pfad: Path) -> Path:
    Image.new("RGB", (8, 8), (20, 20, 20)).save(pfad)
    return pfad


def _ablage(handler) -> ImgbbAblage:
    a = ImgbbAblage("geheim")
    a.client = httpx.Client(transport=httpx.MockTransport(handler))
    return a


def test_ein_bild_bekommt_eine_adresse(tmp_path):
    def antworte(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"url": "https://i.test/abc.png"}})

    adresse = _ablage(antworte).lade_hoch(_bild(tmp_path / "b.png"))

    assert adresse == "https://i.test/abc.png"


def test_das_bild_geht_wirklich_mit(tmp_path):
    gesehen: dict[str, str] = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        gesehen.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        gesehen["key"] = request.url.params["key"]
        gesehen["expiration"] = request.url.params["expiration"]
        return httpx.Response(200, json={"data": {"url": "https://i.test/a.png"}})

    pfad = _bild(tmp_path / "beitrag.png")
    _ablage(antworte).lade_hoch(pfad)

    assert gesehen["key"] == "geheim"
    assert gesehen["name"] == "beitrag"
    # Hochgeladen wird das echte Bild - aber als JPEG, denn nur das nimmt
    # Instagram an. Die Datei auf der Platte bleibt, wie sie war.
    hochgeladen = base64.b64decode(gesehen["image"])
    assert hochgeladen == fuer_instagram(pfad)
    assert hochgeladen[:2] == b"\xff\xd8"
    with Image.open(io.BytesIO(hochgeladen)) as kopie:
        assert kopie.format == "JPEG"
        assert kopie.size == (8, 8)


def test_die_bilder_bleiben_nicht_fuer_immer_liegen(tmp_path):
    """Instagram holt in Sekunden ab - danach hat es seine eigene Kopie."""
    gesehen: dict[str, str] = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        gesehen["expiration"] = request.url.params["expiration"]
        return httpx.Response(200, json={"data": {"url": "https://i.test/a.png"}})

    _ablage(antworte).lade_hoch(_bild(tmp_path / "b.png"))

    assert int(gesehen["expiration"]) == HALTBARKEIT_SEKUNDEN
    # imgbb erlaubt 60 bis 15552000 Sekunden.
    assert 60 <= HALTBARKEIT_SEKUNDEN <= 15_552_000


def test_ein_fehlendes_bild_wirft_verstaendlich(tmp_path):
    with pytest.raises(Ablagefehler, match="gibt es nicht"):
        _ablage(lambda r: httpx.Response(200)).lade_hoch(tmp_path / "weg.png")


def test_eine_antwort_ohne_adresse_wirft(tmp_path):
    a = _ablage(lambda r: httpx.Response(200, json={"data": {}}))

    with pytest.raises(Ablagefehler, match="Keine Adresse"):
        a.lade_hoch(_bild(tmp_path / "b.png"))


@pytest.mark.parametrize(
    "code,erwartet", [(401, "Schlüssel"), (413, "zu groß"), (429, "Zu viele")]
)
def test_fehler_werden_auf_deutsch_erklaert(code, erwartet):
    assert erwartet in _lesbar(httpx.Response(code))


def test_ohne_schluessel_gibt_es_keine_ablage():
    assert baue_ablage("imgbb", None) is None
    assert baue_ablage("gibtsnicht", "token") is None


# --- Zusammenspiel mit dem Veröffentlichen --------------------------------


class StreikendeAblage:
    name = "streik"

    def lade_hoch(self, bild):
        raise Ablagefehler("Zu viele Uploads auf einmal.")


class GuteAblage:
    name = "gut"

    def __init__(self):
        self.hochgeladen: list[Path] = []

    def lade_hoch(self, bild):
        self.hochgeladen.append(bild)
        return "https://i.test/fertig.png"


def _verlag(ablage, tmp_path):
    from insta_agent.instagram.publisher import Publisher

    return Publisher(
        client=None,
        media_dir=tmp_path,
        draft_dir=tmp_path / "drafts",
        public_base_url=None,
        live=True,
        ablage=ablage,
    )


def test_ohne_ablage_gibt_es_keine_adresse(tmp_path):
    assert _verlag(None, tmp_path)._public_url(_bild(tmp_path / "b.png")) is None


def test_mit_ablage_entsteht_eine_adresse(tmp_path):
    ablage = GuteAblage()

    adresse = _verlag(ablage, tmp_path)._public_url(_bild(tmp_path / "b.png"))

    assert adresse == "https://i.test/fertig.png"
    assert len(ablage.hochgeladen) == 1


def test_eine_streikende_ablage_bricht_nichts_ab(tmp_path):
    """Der Beitrag bleibt freigegeben und wird beim naechsten Mal erneut versucht."""
    adresse = _verlag(StreikendeAblage(), tmp_path)._public_url(_bild(tmp_path / "b.png"))

    assert adresse is None


def test_ein_eigener_oeffentlicher_ordner_hat_vorrang(tmp_path):
    """Wer ihn eingerichtet hat, will ihn auch benutzen."""
    from insta_agent.instagram.publisher import Publisher

    ablage = GuteAblage()
    verlag = Publisher(
        client=None,
        media_dir=tmp_path,
        draft_dir=tmp_path / "drafts",
        public_base_url="https://eigener.test/bilder",
        live=True,
        ablage=ablage,
    )

    adresse = verlag._public_url(_bild(tmp_path / "b.png"))

    # Auch hier geht die JPEG-Fassung hinaus, nicht das PNG.
    assert adresse == "https://eigener.test/bilder/b-ig.jpg"
    assert ablage.hochgeladen == []


def test_veroeffentlichen_ist_erst_mit_einem_weg_zur_adresse_moeglich():
    """Ohne Adresse, von der Instagram das Bild holt, geht gar nichts."""
    from insta_agent.config import Settings

    s = Settings()
    s.ig_user_id, s.ig_access_token = "1", "t"
    s.ablage_anbieter = "imgbb"  # braucht einen Schlüssel
    assert s.instagram_ready
    assert not s.can_publish

    s.ablage_token = "abc"
    assert s.can_publish


def test_ein_bildspeicher_ohne_schluessel_ist_sofort_bereit():
    """Sonst müsste sich der Betreiber erst irgendwo anmelden, um zu posten."""
    from insta_agent.config import Settings

    s = Settings()
    s.ig_user_id, s.ig_access_token = "1", "t"

    assert s.ablage_anbieter in OHNE_SCHLUESSEL
    assert s.ablage_token is None
    assert s.can_publish


# --- Der Hauptschalter ----------------------------------------------------


def test_eingerichtet_heisst_noch_nicht_scharf():
    """Die Sicherung muss einmal bewusst umgelegt werden."""
    from insta_agent.config import Settings

    s = Settings()
    s.ig_user_id, s.ig_access_token, s.ablage_token = "1", "t", "a"

    assert s.can_publish
    assert not s.postet_wirklich  # posting.live ist aus

    s.posting.live = True
    assert s.postet_wirklich


def test_scharf_allein_reicht_nicht():
    """Ohne Zugang nuetzt der Schalter nichts."""
    from insta_agent.config import Settings

    s = Settings()
    s.posting.live = True

    assert not s.can_publish
    assert not s.postet_wirklich


@pytest.mark.parametrize("wert,erwartet", [
    ("true", True), ("1", True), ("ja", True), ("an", True), ("WAHR", True),
    ("false", False), ("0", False), ("nein", False), ("", False),
])
def test_der_schalter_versteht_deutsch_und_englisch(wert, erwartet, monkeypatch):
    from insta_agent.config import load_settings

    monkeypatch.setenv("POSTING_LIVE", wert)
    assert load_settings().posting.live is erwartet


# --- Bildspeicher ohne Konto ---------------------------------------------


def _catbox(handler, klasse=None):
    from insta_agent.instagram.ablage import LitterboxAblage

    a = (klasse or LitterboxAblage)()
    a.client = httpx.Client(transport=httpx.MockTransport(handler))
    return a


def test_ohne_schluessel_kommt_trotzdem_eine_adresse(tmp_path):
    def antworte(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="https://litter.catbox.moe/abc.jpg")

    assert _catbox(antworte).lade_hoch(_bild(tmp_path / "b.png")) == (
        "https://litter.catbox.moe/abc.jpg"
    )


def test_auch_ohne_konto_geht_ein_jpeg_hinaus(tmp_path):
    """Derselbe Grund wie überall: Instagram nimmt nichts anderes an."""
    gesehen: dict[str, bytes] = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        gesehen["rumpf"] = request.content
        return httpx.Response(200, text="https://litter.catbox.moe/abc.jpg")

    pfad = _bild(tmp_path / "beitrag.png")
    _catbox(antworte).lade_hoch(pfad)

    assert fuer_instagram(pfad) in gesehen["rumpf"]
    assert b"image/jpeg" in gesehen["rumpf"]
    assert b"beitrag.jpg" in gesehen["rumpf"]
    # Die Datei auf der Platte bleibt ein PNG.
    assert pfad.read_bytes()[:4] == b"\x89PNG"


def test_die_verfallszeit_geht_mit(tmp_path):
    gesehen: dict[str, bytes] = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        gesehen["rumpf"] = request.content
        return httpx.Response(200, text="https://litter.catbox.moe/abc.jpg")

    _catbox(antworte).lade_hoch(_bild(tmp_path / "b.png"))

    assert b"fileupload" in gesehen["rumpf"]
    assert b"24h" in gesehen["rumpf"]


def test_ein_dauerhafter_speicher_schickt_keine_verfallszeit(tmp_path):
    from insta_agent.instagram.ablage import CatboxAblage

    gesehen: dict[str, bytes] = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        gesehen["rumpf"] = request.content
        return httpx.Response(200, text="https://files.catbox.moe/abc.jpg")

    _catbox(antworte, CatboxAblage).lade_hoch(_bild(tmp_path / "b.png"))

    assert b"time" not in gesehen["rumpf"]


def test_eine_fehlermeldung_statt_einer_adresse_wirft(tmp_path):
    """Catbox antwortet mit 200 und Klartext - auch im Fehlerfall."""
    from insta_agent.instagram.ablage import Ablagefehler

    a = _catbox(lambda r: httpx.Response(200, text="File too large"))

    with pytest.raises(Ablagefehler, match="Keine Adresse"):
        a.lade_hoch(_bild(tmp_path / "b.png"))


# --- Die Kette ------------------------------------------------------------


def test_der_eingestellte_speicher_kommt_zuerst():
    from insta_agent.instagram.ablage import baue_ablagen

    assert [a.name for a in baue_ablagen("catbox", "abc")][0] == "catbox"


def test_hinter_dem_eingestellten_stehen_die_anderen_bereit():
    """Ob Meta eine Adresse annimmt, weiss man erst beim Versuch."""
    from insta_agent.instagram.ablage import baue_ablagen

    namen = [a.name for a in baue_ablagen("imgbb", "abc")]

    assert len(namen) > 1
    assert len(namen) == len(set(namen))


def test_ohne_schluessel_faellt_imgbb_aus_der_kette():
    from insta_agent.instagram.ablage import baue_ablagen

    assert "imgbb" not in [a.name for a in baue_ablagen("litterbox", None)]


def test_imgbb_steht_hinten():
    """Meta lehnt Adressen von dort ab - erst versuchen, was funktioniert."""
    from insta_agent.instagram.ablage import KETTE

    assert KETTE[-1] == "imgbb"


def test_ein_gesperrter_speicher_kommt_nie_zuerst_dran():
    """Sonst kostet jeder Beitrag erst einen Fehlschlag, bevor es klappt."""
    from insta_agent.instagram.ablage import NIE_ZUERST, baue_ablagen

    for gesperrt in NIE_ZUERST:
        namen = [a.name for a in baue_ablagen(gesperrt, "abc")]
        assert namen[0] != gesperrt
        # Verschwinden soll er aber nicht - vielleicht geht es wieder.
        assert gesperrt in namen
