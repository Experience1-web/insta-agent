"""Bilderzeugung - und was passiert, wenn der Dienst nicht liefert.

Der wichtigste Fall ist nicht der Erfolg, sondern der Fehlschlag: Ein
streikender Bilddienst darf nie einen bezahlten Denkzyklus wegwerfen.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from PIL import Image

from insta_agent.config import BildConfig, EconomyConfig, LLMConfig, PostingConfig, Settings
from insta_agent.imaging.generator import (
    Bildfehler,
    ReplicateGenerator,
    _erste_bildadresse,
    _lesbarer_fehler,
    baue_generator,
)
from insta_agent.imaging.overlay import lege_hook_auf
from insta_agent.models import VisualSpec

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _generator(handler, modell="black-forest-labs/flux-1.1-pro") -> ReplicateGenerator:
    g = ReplicateGenerator("geheim", modell)
    g.client = httpx.Client(transport=httpx.MockTransport(handler))
    return g


# --- Der gute Fall --------------------------------------------------------


def _mit_bild(handler) -> ReplicateGenerator:
    """Ein Generator, der statt herunterzuladen ein fertiges PNG liefert."""
    g = _generator(handler)
    g.hol_bytes = lambda url: PNG
    return g


def test_ein_fertiges_bild_wird_gespeichert(tmp_path):
    def antworte(request: httpx.Request) -> httpx.Response:
        assert request.headers["Prefer"] == "wait"
        return httpx.Response(
            201, json={"status": "succeeded", "output": ["https://beispiel.test/b.png"]}
        )

    ziel = _mit_bild(antworte).erzeuge("a cat", tmp_path / "bild.png")

    assert ziel.exists()
    assert ziel.read_bytes().startswith(b"\x89PNG")


def test_der_prompt_geht_wirklich_hinaus(tmp_path):
    gesehen = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        import json as _json

        gesehen.update(_json.loads(request.content)["input"])
        return httpx.Response(201, json={"status": "succeeded", "output": "https://x.test/b.png"})

    _mit_bild(antworte).erzeuge("a lighthouse at dusk, 9:16", tmp_path / "b.png")

    assert gesehen["prompt"] == "a lighthouse at dusk, 9:16"
    # Hochformat ist nicht verhandelbar - der Account lebt davon.
    assert gesehen["aspect_ratio"] == "9:16"


def test_der_schluessel_geht_nicht_an_den_auslieferungsdienst(tmp_path):
    """Die Bildadresse zeigt auf ein fremdes Netz - unser Token hat da nichts zu suchen."""
    import inspect

    quelle = inspect.getsource(ReplicateGenerator.hol_bytes)
    assert "httpx.Client(timeout=60.0, follow_redirects=True)" in quelle
    assert "self.client" not in quelle
    assert "Authorization" not in quelle


# --- Die schlechten Fälle -------------------------------------------------


@pytest.mark.parametrize(
    "code,erwartet",
    [
        (401, "Schlüssel"),
        (402, "Guthaben"),
        (404, "Modellnamen"),
        (429, "Zu viele Anfragen"),
    ],
)
def test_httpfehler_werden_auf_deutsch_erklaert(code, erwartet):
    antwort = httpx.Response(code, json={"detail": "irgendwas englisches"})
    assert erwartet in _lesbarer_fehler(antwort)


def test_ein_abgelehnter_schluessel_wirft_verstaendlich(tmp_path):
    g = _generator(lambda r: httpx.Response(401, json={"detail": "Unauthenticated"}))

    with pytest.raises(Bildfehler, match="Schlüssel"):
        g.erzeuge("a cat", tmp_path / "b.png")


def test_eine_gescheiterte_erzeugung_wirft(tmp_path):
    g = _generator(
        lambda r: httpx.Response(201, json={"status": "failed", "error": "NSFW erkannt"})
    )

    with pytest.raises(Bildfehler, match="NSFW erkannt"):
        g.erzeuge("a cat", tmp_path / "b.png")


def test_eine_antwort_ohne_bild_wirft(tmp_path):
    g = _generator(lambda r: httpx.Response(201, json={"status": "succeeded", "output": None}))

    with pytest.raises(Bildfehler, match="kein Bild"):
        g.erzeuge("a cat", tmp_path / "b.png")


def test_beide_antwortformen_werden_verstanden():
    """Die Modelle liefern mal eine Liste, mal eine einzelne Adresse."""
    assert _erste_bildadresse(["https://a.test/1.png"]) == "https://a.test/1.png"
    assert _erste_bildadresse("https://a.test/1.png") == "https://a.test/1.png"
    assert _erste_bildadresse([]) is None
    assert _erste_bildadresse(None) is None
    assert _erste_bildadresse([{"url": "x"}]) is None


# --- Ohne Schlüssel -------------------------------------------------------


def test_ohne_schluessel_gibt_es_keinen_generator():
    """Das ist der Normalzustand und kein Fehler."""
    assert baue_generator("replicate", None, "modell") is None
    assert baue_generator("replicate", "", "modell") is None


def test_ein_unbekannter_anbieter_bricht_nichts_ab():
    assert baue_generator("gibtsnicht", "token", "modell") is None


def test_mit_schluessel_entsteht_einer():
    g = baue_generator("replicate", "token", "modell")
    assert g is not None and g.name == "replicate"
    g.close()


# --- Der Hook auf dem Bild ------------------------------------------------


def _foto(pfad: Path, farbe: tuple[int, int, int]) -> Path:
    Image.new("RGB", (1080, 1920), farbe).save(pfad)
    return pfad


def test_der_hook_landet_auf_dem_bild(tmp_path):
    quelle = _foto(tmp_path / "roh.png", (20, 24, 36))
    ziel = lege_hook_auf(
        quelle, tmp_path / "fertig.png",
        text="Dieser Ort existiert nicht.",
        spec=VisualSpec(headline="x"),
        handle="@probe",
    )

    fertig = Image.open(ziel)
    assert fertig.size == (1080, 1920)
    # Auf einem einfarbigen Grund muss jetzt mehr als eine Farbe sein.
    assert len(fertig.convert("RGB").getcolors(maxcolors=100000) or []) > 3


def test_ein_bild_in_falscher_groesse_wird_zurechtgerueckt(tmp_path):
    quelle = tmp_path / "quer.png"
    Image.new("RGB", (1200, 800), (30, 30, 30)).save(quelle)

    ziel = lege_hook_auf(
        quelle, tmp_path / "fertig.png",
        text="Kurz", spec=VisualSpec(headline="x"),
    )

    assert Image.open(ziel).size == (1080, 1920)


def test_auf_hellem_grund_wird_ein_schleier_gelegt(tmp_path):
    """Sonst steht weißer Text auf weißem Himmel und ist unsichtbar."""
    hell = _foto(tmp_path / "hell.png", (240, 238, 230))
    dunkel = _foto(tmp_path / "dunkel.png", (18, 20, 28))

    a = Image.open(lege_hook_auf(hell, tmp_path / "a.png", text="Test Satz",
                                 spec=VisualSpec(headline="x", text_hex="#FFFFFF")))
    b = Image.open(lege_hook_auf(dunkel, tmp_path / "b.png", text="Test Satz",
                                 spec=VisualSpec(headline="x", text_hex="#FFFFFF")))

    # Im oberen Bereich muss das helle Bild abgedunkelt worden sein.
    oben_hell = a.crop((0, 260, 1080, 400)).resize((8, 8))
    mittel = sum(p[0] for p in oben_hell.getdata()) / 64
    assert mittel < 240, "Der Schleier hat nicht gegriffen"
    # Das dunkle Bild braucht keinen und behält seinen Grund.
    oben_dunkel = b.crop((0, 900, 1080, 1000)).resize((8, 8))
    assert sum(p[0] for p in oben_dunkel.getdata()) / 64 < 40


# --- Im Zyklus ------------------------------------------------------------


class StreikenderDienst:
    name = "streik"

    def erzeuge(self, prompt, ziel):
        raise Bildfehler("Das Guthaben beim Bilddienst ist aufgebraucht.")


class LiefernderDienst:
    name = "liefert"

    def __init__(self):
        self.prompts: list[str] = []

    def erzeuge(self, prompt, ziel):
        self.prompts.append(prompt)
        Image.new("RGB", (1080, 1920), (24, 28, 40)).save(ziel)
        return ziel


@pytest.fixture
def agent(tmp_path, monkeypatch):
    from insta_agent.runner import Agent
    from tests.test_cycle import FakeBrain

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(
        Settings(
            llm=LLMConfig(),
            economy=EconomyConfig(treasury_start_usd=5.0, max_cost_per_cycle_usd=2.0),
            posting=PostingConfig(posts_per_day=1, live=False),
            bild=BildConfig(kosten_pro_bild_usd=0.04),
            db_path=tmp_path / "agent.db",
            media_dir=tmp_path / "media",
            draft_dir=tmp_path / "drafts",
        )
    )
    yield a
    a.close()


def test_ein_streikender_bilddienst_kostet_nicht_den_zyklus(agent):
    """Der teure Teil ist das Denken. Das darf ein fehlendes Bild nie wegwerfen."""
    agent.bildgenerator = StreikenderDienst()

    bericht = agent.run_cycle()

    assert bericht.halted_reason is None
    entwurf = agent.store.pending_drafts()[0]
    # Es gibt trotzdem ein Bild - die typografische Fassung.
    assert Path(entwurf["image_path"]).exists()
    assert any("Bild nicht erzeugt" in s for s in bericht.steps)


def test_ein_fehlschlag_wird_nicht_berechnet(agent):
    agent.bildgenerator = StreikenderDienst()
    vorher = agent.treasury.state().spent_usd

    agent.run_cycle()

    bildkosten = [
        z for z in agent.store.ledger_entries(limit=50) if z["category"] == "image"
    ]
    assert bildkosten == []
    assert agent.treasury.state().spent_usd > vorher  # Denken kostete trotzdem


def test_ein_geliefertes_bild_wird_gebucht(agent):
    agent.bildgenerator = LiefernderDienst()

    agent.run_cycle()

    bildkosten = [
        z for z in agent.store.ledger_entries(limit=50) if z["category"] == "image"
    ]
    assert len(bildkosten) == 1
    assert abs(bildkosten[0]["amount_usd"]) == pytest.approx(0.04)


def test_der_geschriebene_prompt_geht_an_den_dienst(agent):
    dienst = LiefernderDienst()
    agent.bildgenerator = dienst

    agent.run_cycle()

    assert len(dienst.prompts) == 1
    assert dienst.prompts[0].strip()


def test_ohne_prompt_wird_kein_bild_bestellt(agent):
    """Ein alter Entwurf ohne Bildbeschreibung soll nichts kosten."""
    dienst = LiefernderDienst()
    agent.bildgenerator = dienst

    from insta_agent.brain import content as inhalt

    echt = inhalt.create_post_draft

    def ohne_prompt(*a, **k):
        entwurf = echt(*a, **k)
        entwurf.image_generation_prompt = "   "
        return entwurf

    monkeypatch_ziel = "insta_agent.runner.create_post_draft"
    import insta_agent.runner as r

    alt = r.create_post_draft
    r.create_post_draft = ohne_prompt
    try:
        agent.run_cycle()
    finally:
        r.create_post_draft = alt

    assert dienst.prompts == []
    assert [z for z in agent.store.ledger_entries(50) if z["category"] == "image"] == []


# --- Der kostenlose Weg: eigener Rechner ----------------------------------

import base64  # noqa: E402

from insta_agent.imaging.generator import LokalerGenerator  # noqa: E402


def _lokal(handler) -> LokalerGenerator:
    g = LokalerGenerator("http://127.0.0.1:7860")
    g.client = httpx.Client(transport=httpx.MockTransport(handler))
    return g


def test_der_lokale_weg_braucht_keinen_schluessel():
    """Was auf dem eigenen Rechner laeuft, muss sich nirgends ausweisen."""
    g = baue_generator("lokal", None, "")
    assert g is not None and g.name == "lokal"
    assert g.adresse == "http://127.0.0.1:7860"
    g.close()


def test_eine_eigene_adresse_wird_uebernommen():
    g = baue_generator("lokal", "http://192.168.0.5:7860/", "")
    assert g.adresse == "http://192.168.0.5:7860"
    g.close()


def test_das_lokale_bild_wird_entschluesselt_und_gespeichert(tmp_path):
    def antworte(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"images": [base64.b64encode(PNG).decode()]})

    ziel = _lokal(antworte).erzeuge("a lighthouse", tmp_path / "b.png")

    assert ziel.read_bytes() == PNG


def test_ein_datentyp_vorspann_stoert_nicht(tmp_path):
    """Manche Fassungen schicken "data:image/png;base64,..." zurueck."""
    def antworte(request: httpx.Request) -> httpx.Response:
        daten = "data:image/png;base64," + base64.b64encode(PNG).decode()
        return httpx.Response(200, json={"images": [daten]})

    assert _lokal(antworte).erzeuge("x", tmp_path / "b.png").read_bytes() == PNG


def test_das_lokale_bild_ist_hochformat(tmp_path):
    gesehen = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        import json as _json

        gesehen.update(_json.loads(request.content))
        return httpx.Response(200, json={"images": [base64.b64encode(PNG).decode()]})

    _lokal(antworte).erzeuge("x", tmp_path / "b.png")

    assert round(gesehen["height"] / gesehen["width"], 2) == round(16 / 9, 2)
    # Beide Maße muessen durch 8 teilbar sein, sonst lehnt das Modell ab.
    assert gesehen["width"] % 8 == 0 and gesehen["height"] % 8 == 0
    # Schrift im erzeugten Bild wuerde mit dem Hook kollidieren.
    assert "text" in gesehen["negative_prompt"]


def test_ein_nicht_laufendes_programm_wird_erklaert(tmp_path):
    def verweigere(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(Bildfehler, match="Läuft das Bildprogramm"):
        _lokal(verweigere).erzeuge("x", tmp_path / "b.png")


def test_ein_programm_ohne_api_wird_erklaert(tmp_path):
    g = _lokal(lambda r: httpx.Response(404))

    with pytest.raises(Bildfehler, match="--api"):
        g.erzeuge("x", tmp_path / "b.png")


def test_eine_zu_langsame_grafikkarte_wird_erklaert(tmp_path):
    def zu_langsam(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("zu lange")

    with pytest.raises(Bildfehler, match="Grafikkarte"):
        _lokal(zu_langsam).erzeuge("x", tmp_path / "b.png")


def test_lokal_erzeugte_bilder_kosten_nichts(agent):
    """Der eigene Rechner taucht nicht in der Kasse auf."""
    agent.bildgenerator = LiefernderDienst()
    agent.settings.bild.kosten_pro_bild_usd = 0.0

    agent.run_cycle()

    assert [z for z in agent.store.ledger_entries(50) if z["category"] == "image"] == []
    # Das Bild ist trotzdem da.
    assert Path(agent.store.pending_drafts()[0]["image_path"]).exists()


# --- Der kostenlose Weg mit Schluessel: Gemini ----------------------------

from insta_agent.imaging.generator import (  # noqa: E402
    GeminiGenerator,
    _gemini_bilddaten,
    _gemini_fehler,
)


def _gemini(handler) -> GeminiGenerator:
    g = GeminiGenerator("geheim", "gemini-2.5-flash-image")
    g.client = httpx.Client(transport=httpx.MockTransport(handler))
    return g


def _bildantwort() -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Hier ist dein Bild"},
                        {"inlineData": {"mimeType": "image/png",
                                        "data": base64.b64encode(PNG).decode()}},
                    ]
                }
            }
        ]
    }


def test_gemini_speichert_das_bild(tmp_path):
    ziel = _gemini(lambda r: httpx.Response(200, json=_bildantwort())).erzeuge(
        "a lighthouse", tmp_path / "b.png"
    )
    assert ziel.read_bytes() == PNG


def test_das_bild_wird_auch_zwischen_textteilen_gefunden():
    """Gemini schickt oft erst Text und dann das Bild."""
    assert _gemini_bilddaten(_bildantwort()) == base64.b64encode(PNG).decode()


def test_beide_schreibweisen_werden_verstanden():
    """Die Schnittstelle nutzt inlineData und inline_data nebeneinander."""
    mit_unterstrich = {
        "candidates": [{"content": {"parts": [{"inline_data": {"data": "abc"}}]}}]
    }
    assert _gemini_bilddaten(mit_unterstrich) == "abc"


def test_eine_antwort_ganz_ohne_bild_gibt_none():
    nur_text = {"candidates": [{"content": {"parts": [{"text": "Das mache ich nicht."}]}}]}
    assert _gemini_bilddaten(nur_text) is None
    assert _gemini_bilddaten({}) is None


def test_ein_abgelehnter_prompt_wird_erklaert(tmp_path):
    nur_text = {"candidates": [{"content": {"parts": [{"text": "Nein."}]}}]}

    with pytest.raises(Bildfehler, match="abgelehnt"):
        _gemini(lambda r: httpx.Response(200, json=nur_text)).erzeuge("x", tmp_path / "b.png")


def test_ein_aufgebrauchtes_freikontingent_wird_erklaert():
    text = _gemini_fehler(httpx.Response(429, json={"error": {"message": "quota"}}))
    assert "kostenlose Kontingent" in text and "Morgen" in text


def test_ein_falscher_schluessel_wird_erklaert():
    for code in (401, 403):
        assert "Schlüssel" in _gemini_fehler(httpx.Response(code, json={}))


def test_ein_abgelehnter_formatwunsch_wird_ohne_ihn_wiederholt(tmp_path):
    """Aeltere Bildmodelle kennen aspectRatio nicht - das darf nichts kosten."""
    versuche = []

    def antworte(request: httpx.Request) -> httpx.Response:
        import json as _json

        koerper = _json.loads(request.content)
        versuche.append("imageConfig" in koerper["generationConfig"])
        if versuche[-1]:
            return httpx.Response(400, json={"error": {"message": "Unknown field imageConfig"}})
        return httpx.Response(200, json=_bildantwort())

    ziel = _gemini(antworte).erzeuge("x", tmp_path / "b.png")

    assert versuche == [True, False]
    assert ziel.read_bytes() == PNG


def test_der_formatwunsch_wird_zuerst_gestellt(tmp_path):
    gesehen = {}

    def antworte(request: httpx.Request) -> httpx.Response:
        import json as _json

        gesehen.update(_json.loads(request.content)["generationConfig"])
        return httpx.Response(200, json=_bildantwort())

    _gemini(antworte).erzeuge("x", tmp_path / "b.png")

    assert gesehen["imageConfig"]["aspectRatio"] == "9:16"
    assert gesehen["responseModalities"] == ["IMAGE"]


# --- Jedes Format wird zurechtgeschnitten, nie gezerrt --------------------


@pytest.mark.parametrize("masse", [(1024, 1024), (1920, 1080), (792, 1408), (1080, 1920)])
def test_jedes_seitenverhaeltnis_wird_beschnitten_statt_gezerrt(tmp_path, masse):
    """Nicht jeder Anbieter kann 9:16. Zerren sieht man sofort."""
    from insta_agent.imaging.overlay import _auf_hochformat

    quelle = tmp_path / "roh.png"
    Image.new("RGB", masse, (40, 40, 40)).save(quelle)

    assert _auf_hochformat(Image.open(quelle)).size == (1080, 1920)


def test_beim_beschneiden_bleibt_der_bildausschnitt_unverzerrt(tmp_path):
    """Ein Kreis muss ein Kreis bleiben."""
    from insta_agent.imaging.overlay import _auf_hochformat

    quadrat = Image.new("RGB", (1024, 1024), (0, 0, 0))
    from PIL import ImageDraw

    ImageDraw.Draw(quadrat).ellipse([(312, 312), (712, 712)], fill=(255, 255, 255))

    zugeschnitten = _auf_hochformat(quadrat)
    # Der Kreis wird um denselben Faktor skaliert - Breite und Hoehe der
    # weissen Flaeche muessen im selben Verhaeltnis zueinander stehen.
    weiss = zugeschnitten.convert("L").point(lambda w: 255 if w > 128 else 0)
    kasten = weiss.getbbox()
    breite, hoehe = kasten[2] - kasten[0], kasten[3] - kasten[1]
    assert abs(breite - hoehe) < 12, f"verzerrt: {breite}x{hoehe}"
