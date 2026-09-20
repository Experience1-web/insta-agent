"""Der öffentliche Platz für die Bilder.

Wichtig ist auch hier der Fehlschlag: Wenn das Ablegen nicht klappt,
darf der Beitrag nicht verlorengehen - er bleibt freigegeben und wird
beim nächsten Zyklus erneut versucht.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
from PIL import Image

from insta_agent.instagram.ablage import (
    HALTBARKEIT_SEKUNDEN,
    Ablagefehler,
    ImgbbAblage,
    _lesbar,
    baue_ablage,
)


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
    # Die Bilddaten müssen die des echten Bildes sein.
    assert base64.b64decode(gesehen["image"]) == pfad.read_bytes()


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

    assert adresse == "https://eigener.test/bilder/b.png"
    assert ablage.hochgeladen == []


def test_veroeffentlichen_ist_erst_mit_einem_weg_zur_adresse_moeglich():
    from insta_agent.config import Settings

    s = Settings()
    s.ig_user_id, s.ig_access_token = "1", "t"
    assert s.instagram_ready
    assert not s.can_publish

    s.ablage_token = "abc"
    assert s.can_publish
