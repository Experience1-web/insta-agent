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
    assert "insta-agent ablage" in result.reason
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


# --- Wenn Instagram die Adresse nicht mag ---------------------------------


class GesperrterClient(FakeClient):
    """Instagram lehnt bestimmte Adressen ab - mit einer Meldung übers Bild.

    Genau das passiert mit imgbb: Metas Abholer kommt nicht an die Datei,
    und zurück kommt "Only photo or video can be accepted as media type".
    """

    def __init__(self, gesperrt: str):
        super().__init__()
        self.gesperrt = gesperrt

    def create_container(self, image_url, caption):
        from insta_agent.instagram.client import GraphAPIError

        self.calls.append(("container", image_url, caption))
        if self.gesperrt in image_url:
            raise GraphAPIError(
                "OAuthException 9004: Only photo or video can be accepted as media type."
            )
        return "container-1"


class FakeAblage:
    def __init__(self, name, adresse):
        self.name = name
        self.adresse = adresse
        self.hochgeladen = 0

    def lade_hoch(self, bild):
        self.hochgeladen += 1
        return self.adresse


def test_eine_abgelehnte_adresse_wird_woanders_nochmal_versucht(tmp_path, draft):
    client = GesperrterClient("ibb.co")
    erste = FakeAblage("imgbb", "https://i.ibb.co/x/b.jpg")
    zweite = FakeAblage("litterbox", "https://litter.catbox.moe/b.jpg")

    publisher = _publisher(tmp_path, live=True, client=client, ablagen=[erste, zweite])
    result = publisher.publish(draft, tmp_path / "media" / "bild.png")

    assert result.published is True
    assert result.ig_media_id == "media-99"
    assert [c[1] for c in client.calls if c[0] == "container"] == [
        "https://i.ibb.co/x/b.jpg",
        "https://litter.catbox.moe/b.jpg",
    ]


def test_solange_es_klappt_wird_nichts_zweites_hochgeladen(tmp_path, draft):
    """Jeder Upload kostet Zeit - die zweite Ablage bleibt unberührt."""
    erste = FakeAblage("litterbox", "https://litter.catbox.moe/b.jpg")
    zweite = FakeAblage("catbox", "https://files.catbox.moe/b.jpg")

    publisher = _publisher(
        tmp_path, live=True, client=FakeClient(), ablagen=[erste, zweite]
    )
    publisher.publish(draft, tmp_path / "media" / "bild.png")

    assert erste.hochgeladen == 1
    assert zweite.hochgeladen == 0


def test_ein_fehler_der_nicht_an_der_adresse_liegt_bricht_ab(tmp_path, draft):
    """Ein abgelaufenes Zugangswort wird durch einen anderen Speicher nicht besser."""
    from insta_agent.instagram.client import GraphAPIError

    class AbgelaufenerClient(FakeClient):
        def create_container(self, image_url, caption):
            self.calls.append(("container", image_url, caption))
            raise GraphAPIError("OAuthException 190: Session has expired")

    client = AbgelaufenerClient()
    zweite = FakeAblage("catbox", "https://files.catbox.moe/b.jpg")
    publisher = _publisher(
        tmp_path,
        live=True,
        client=client,
        ablagen=[FakeAblage("litterbox", "https://litter.catbox.moe/b.jpg"), zweite],
    )
    result = publisher.publish(draft, tmp_path / "media" / "bild.png")

    assert result.published is False
    assert zweite.hochgeladen == 0
    assert "190" in result.reason


def test_ein_speicher_der_nicht_annimmt_haelt_die_kette_nicht_auf(tmp_path, draft):
    class KaputteAblage:
        name = "kaputt"

        def lade_hoch(self, bild):
            raise RuntimeError("Netz weg")

    client = FakeClient()
    publisher = _publisher(
        tmp_path,
        live=True,
        client=client,
        ablagen=[KaputteAblage(), FakeAblage("catbox", "https://files.catbox.moe/b.jpg")],
    )
    result = publisher.publish(draft, tmp_path / "media" / "bild.png")

    assert result.published is True


def test_wenn_alles_scheitert_stehen_alle_gruende_da(tmp_path, draft):
    client = GesperrterClient("")  # lehnt jede Adresse ab
    publisher = _publisher(
        tmp_path,
        live=True,
        client=client,
        ablagen=[
            FakeAblage("imgbb", "https://i.ibb.co/x/b.jpg"),
            FakeAblage("litterbox", "https://litter.catbox.moe/b.jpg"),
        ],
    )
    result = publisher.publish(draft, tmp_path / "media" / "bild.png")

    assert result.published is False
    assert "i.ibb.co" in result.reason
    assert "litter.catbox.moe" in result.reason
    assert result.draft_path.exists()


# --- Der Handlungsaufruf steht nur einmal da ------------------------------


def test_ein_fast_gleicher_aufruf_wird_nicht_nochmal_angehaengt(draft):
    """Er schreibt den Aufruf gern in den Text und noch einmal ins Feld.

    Beim zweiten Mal leicht erweitert - wörtlich verglichen faellt das
    nicht auf, untereinander gedruckt schon.
    """
    draft.caption = (
        "25 Tage. So viel Zeit mit deiner Mutter ist statistisch noch übrig.\n\n"
        "Schick das der Person, die letzte Woche gesagt hat, sie habe gerade keine Zeit."
    )
    draft.call_to_action = (
        "Schick das der Person, die letzte Woche gesagt hat, sie habe gerade keine "
        "Zeit – und folge, wenn du lieber mit einer Quelle streitest als mit einem Gefühl."
    )

    caption = Publisher.full_caption(draft)

    assert caption.count("Schick das der Person") == 1


def test_ein_eigener_aufruf_kommt_weiterhin_dazu(draft):
    draft.caption = "Zwei Zahlen, ein Irrtum weniger."
    draft.call_to_action = "Speichere das für den nächsten Streit am Küchentisch."

    assert "Küchentisch" in Publisher.full_caption(draft)
