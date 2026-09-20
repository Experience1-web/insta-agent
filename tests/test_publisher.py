"""Ohne ausdrückliches Live-Schalten darf nichts nach außen gehen."""

from PIL import Image

from insta_agent.instagram.publisher import Publisher


def _publisher(tmp_path, **kwargs):
    defaults = dict(
        client=None,
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
        public_base_url=None,
        live=False,
    )
    defaults.update(kwargs)
    return Publisher(**defaults)


class FakeClient:
    """Ein Instagram-Client, der nur mitschreibt statt zu senden."""

    def __init__(self):
        self.calls = []

    def create_container(self, image_url, caption):
        self.calls.append(("container", image_url, caption))
        return "container-1"

    def wait_until_ready(self, container_id):
        self.calls.append(("warten", container_id))

    def publish_container(self, container_id):
        self.calls.append(("veröffentlichen", container_id))
        return "media-99"


def test_trockenlauf_schreibt_nur_eine_datei(tmp_path, draft):
    publisher = _publisher(tmp_path)
    result = publisher.publish(draft, tmp_path / "media" / "bild.png")

    assert result.published is False
    assert result.reason == "Trockenlauf"
    assert result.draft_path.exists()
    assert "Niemand folgt dir" in result.draft_path.read_text(encoding="utf-8")


def test_live_ohne_zugangsdaten_veroeffentlicht_nicht(tmp_path, draft):
    publisher = _publisher(tmp_path, live=True, public_base_url="https://beispiel.de/m")
    result = publisher.publish(draft, tmp_path / "media" / "bild.png")

    assert result.published is False
    assert "Zugangsdaten" in result.reason
    assert result.draft_path.exists()


def test_live_ohne_oeffentliche_url_veroeffentlicht_nicht(tmp_path, draft):
    """Die Graph API holt das Bild selbst - ohne URL geht es nicht."""
    client = FakeClient()
    publisher = _publisher(tmp_path, live=True, client=client)
    result = publisher.publish(draft, tmp_path / "media" / "bild.png")

    assert result.published is False
    assert "PUBLIC_MEDIA_BASE_URL" in result.reason
    assert client.calls == []


def test_live_mit_allem_noetigen_veroeffentlicht(tmp_path, draft):
    client = FakeClient()
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True)
    image = media_dir / "bild.png"
    Image.new("RGB", (1080, 1350), (10, 10, 10)).save(image)

    publisher = _publisher(
        tmp_path, live=True, client=client, public_base_url="https://beispiel.de/m/"
    )
    result = publisher.publish(draft, image)

    assert result.published is True
    assert result.ig_media_id == "media-99"
    # Hinausgegangen ist die JPEG-Fassung - nur die nimmt Instagram an.
    assert client.calls[0][1] == "https://beispiel.de/m/bild-ig.jpg"
    assert (media_dir / "bild-ig.jpg").is_file()
    assert image.read_bytes()[:4] == b"\x89PNG"


def test_bild_ausserhalb_des_medienordners_wird_abgelehnt(tmp_path, draft):
    """Eine Datei, die nicht öffentlich liegt, hat auch keine gültige URL."""
    client = FakeClient()
    publisher = _publisher(
        tmp_path, live=True, client=client, public_base_url="https://beispiel.de/m"
    )
    fremd = tmp_path / "woanders" / "bild.png"
    fremd.parent.mkdir(parents=True)
    fremd.write_bytes(b"png")

    result = publisher.publish(draft, fremd)
    assert result.published is False
    assert client.calls == []


def test_caption_enthaelt_hashtags_und_handlungsaufruf(draft):
    caption = Publisher.full_caption(draft)
    assert draft.caption in caption
    assert "Speichere das für Montag." in caption
    assert "#wachstum" in caption


def test_handlungsaufruf_wird_nicht_doppelt_angehaengt(draft):
    draft.caption = f"{draft.caption}\n\n{draft.call_to_action}"
    caption = Publisher.full_caption(draft)
    assert caption.count("Speichere das für Montag.") == 1
