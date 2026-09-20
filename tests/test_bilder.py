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


# --- Leonardo --------------------------------------------------------------


def _leonardo(handler):
    import httpx

    from insta_agent.imaging.generator import LeonardoGenerator

    g = LeonardoGenerator("prod-schluessel")
    g.client = httpx.Client(transport=httpx.MockTransport(handler))
    g.hol_bytes = lambda url: b"\x89PNG-bild"
    return g


def test_leonardo_gibt_erst_auf_und_fragt_dann_nach(tmp_path):
    """Die Schnittstelle arbeitet in zwei Schritten."""
    import httpx

    wege = []

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        wege.append((anfrage.method, anfrage.url.path))
        if anfrage.method == "POST":
            return httpx.Response(200, json={"sdGenerationJob": {"generationId": "abc"}})
        return httpx.Response(200, json={"generations_by_pk": {
            "status": "COMPLETE", "generated_images": [{"url": "https://cdn.test/b.png"}]}})

    ziel = _leonardo(antworte).erzeuge("ein Flur mit hartem Licht", tmp_path / "b.png")

    assert ziel.read_bytes() == b"\x89PNG-bild"
    assert [w[0] for w in wege] == ["POST", "GET"]
    assert wege[1][1].endswith("/generations/abc")


def test_leonardo_wartet_bis_das_bild_fertig_ist(tmp_path, monkeypatch):
    import httpx

    monkeypatch.setattr("insta_agent.imaging.generator.time.sleep", lambda s: None)
    zustaende = iter(["PENDING", "PENDING", "COMPLETE"])

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        if anfrage.method == "POST":
            return httpx.Response(200, json={"sdGenerationJob": {"generationId": "abc"}})
        stand = next(zustaende)
        return httpx.Response(200, json={"generations_by_pk": {
            "status": stand,
            "generated_images": [{"url": "https://cdn.test/b.png"}] if stand == "COMPLETE" else [],
        }})

    assert _leonardo(antworte).erzeuge("x", tmp_path / "b.png").exists()


def test_der_schluessel_geht_nie_an_den_bildspeicher():
    """Dieselbe Regel wie bei Replicate: Der Schluessel bleibt bei Leonardo."""
    import inspect

    from insta_agent.imaging.generator import LeonardoGenerator

    quelle = inspect.getsource(LeonardoGenerator.hol_bytes)
    assert "self.client" not in quelle
    assert "httpx.Client(" in quelle


def test_ein_webseiten_schluessel_wird_verstaendlich_abgewiesen(tmp_path):
    import httpx

    from insta_agent.imaging.generator import Bildfehler

    g = _leonardo(lambda a: httpx.Response(401, json={"error": "unauthorized"}))

    with pytest.raises(Bildfehler, match="Produktions"):
        g.erzeuge("x", tmp_path / "b.png")


def test_leeres_guthaben_sagt_was_zu_tun_ist(tmp_path):
    import httpx

    from insta_agent.imaging.generator import Bildfehler

    g = _leonardo(lambda a: httpx.Response(402, json={"error": "no credits"}))

    with pytest.raises(Bildfehler, match="Guthaben"):
        g.erzeuge("x", tmp_path / "b.png")


def test_eine_falsche_modellkennung_wird_erklaert(tmp_path):
    """Eine UUID tippt niemand aus dem Kopf richtig."""
    import httpx

    from insta_agent.imaging.generator import Bildfehler

    g = _leonardo(lambda a: httpx.Response(400, text="unknown model"))

    with pytest.raises(Bildfehler, match="Modell-Kennung"):
        g.erzeuge("x", tmp_path / "b.png")


def test_leonardo_steht_in_der_anbieterliste():
    from insta_agent.imaging.generator import ANBIETER, baue_generator

    assert "leonardo" in ANBIETER
    assert baue_generator("leonardo", "k", "").name == "leonardo"
    # Ohne Schluessel gibt es keinen Generator.
    assert baue_generator("leonardo", None, "") is None


def test_das_format_ist_nah_am_hochformat():
    """4:5 ist Instagrams Feed - und beide Masse muessen durch 8 teilbar sein."""
    from insta_agent.imaging.generator import LeonardoGenerator

    b, h = LeonardoGenerator.BREITE, LeonardoGenerator.HOEHE
    assert b % 8 == 0 and h % 8 == 0
    assert 0.78 <= b / h <= 0.82


# --- Pollinations: ohne Konto, ohne Schluessel -----------------------------


def _pollinations(handler, token=None):
    import httpx

    from insta_agent.imaging.generator import PollinationsGenerator

    g = PollinationsGenerator(token)
    g.client = httpx.Client(transport=httpx.MockTransport(handler))
    return g


def test_pollinations_holt_das_bild_in_einem_aufruf(tmp_path):
    """Der ganze Dienst ist eine Adresse - kein Auftrag, kein Nachfragen."""
    import httpx

    gesehen = {}

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        gesehen["pfad"] = anfrage.url.path
        gesehen["roh"] = str(anfrage.url)
        gesehen["params"] = dict(anfrage.url.params)
        return httpx.Response(200, content=b"\x89PNG-echt",
                              headers={"content-type": "image/png"})

    ziel = _pollinations(antworte).erzeuge("ein Flur mit hartem Licht", tmp_path / "b.png")

    assert ziel.read_bytes() == b"\x89PNG-echt"
    # Der Prompt steht im Pfad und muss dort kodiert sein - sonst zerlegt
    # ein Leerzeichen oder ein Schraegstrich die Adresse.
    assert " " not in gesehen["roh"].split("?")[0]
    assert gesehen["pfad"].endswith("ein Flur mit hartem Licht")
    assert gesehen["params"]["model"] == "flux"


def test_jeder_aufruf_bekommt_eine_andere_saat(tmp_path):
    """Ohne das kaeme bei gleichem Prompt immer dasselbe Bild - und der
    Knopf "Bild neu" waere wirkungslos."""
    import httpx

    saaten = []

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        saaten.append(anfrage.url.params.get("seed"))
        return httpx.Response(200, content=b"x", headers={"content-type": "image/png"})

    g = _pollinations(antworte)
    for i in range(5):
        g.erzeuge("derselbe Prompt", tmp_path / f"b{i}.png")

    assert len(set(saaten)) == 5


def test_ohne_schluessel_geht_kein_schluessel_mit(tmp_path):
    import httpx

    gesehen = {}

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        gesehen.update(dict(anfrage.url.params))
        return httpx.Response(200, content=b"x", headers={"content-type": "image/png"})

    _pollinations(antworte).erzeuge("x", tmp_path / "b.png")

    assert "token" not in gesehen


def test_eine_fehlerseite_wird_nicht_als_bild_gespeichert(tmp_path):
    """Sonst liegt HTML mit der Endung .png im Medienordner."""
    import httpx

    from insta_agent.imaging.generator import Bildfehler

    g = _pollinations(lambda a: httpx.Response(
        200, text="<html>overloaded</html>", headers={"content-type": "text/html"}))

    with pytest.raises(Bildfehler, match="kein Bild"):
        g.erzeuge("x", tmp_path / "b.png")
    assert not (tmp_path / "b.png").exists()


def test_ueberlastung_wird_verstaendlich_gemeldet(tmp_path):
    import httpx

    from insta_agent.imaging.generator import Bildfehler

    g = _pollinations(lambda a: httpx.Response(429))

    with pytest.raises(Bildfehler, match="überlastet"):
        g.erzeuge("x", tmp_path / "b.png")


# --- Cloudflare Workers AI -------------------------------------------------


def _cloudflare(handler, token="konto123:schluessel456"):
    import httpx

    from insta_agent.imaging.generator import CloudflareGenerator

    g = CloudflareGenerator(token)
    g.client = httpx.Client(transport=httpx.MockTransport(handler))
    return g


def test_cloudflare_entschluesselt_das_bild(tmp_path):
    import base64

    import httpx

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        assert "konto123" in str(anfrage.url)
        assert "flux-1-schnell" in str(anfrage.url)
        return httpx.Response(200, json={
            "result": {"image": base64.b64encode(b"\x89PNG-cf").decode()}})

    ziel = _cloudflare(antworte).erzeuge("ein Flur", tmp_path / "b.png")

    assert ziel.read_bytes() == b"\x89PNG-cf"


def test_konto_und_schluessel_stehen_in_einer_einstellung():
    """Zwei Felder waeren eine Stelle mehr, an der man sich vertut."""
    from insta_agent.imaging.generator import CloudflareGenerator

    g = CloudflareGenerator("abc123:geheim")
    assert g.konto == "abc123"
    assert g.schluessel == "geheim"


def test_eine_halbe_angabe_sagt_was_fehlt(tmp_path):
    import httpx

    from insta_agent.imaging.generator import Bildfehler

    g = _cloudflare(lambda a: httpx.Response(200), token="nur-ein-schluessel")

    with pytest.raises(Bildfehler, match="Doppelpunkt"):
        g.erzeuge("x", tmp_path / "b.png")


def test_ein_erschoepftes_tageskontingent_sagt_wann_es_weitergeht(tmp_path):
    import httpx

    from insta_agent.imaging.generator import Bildfehler

    g = _cloudflare(lambda a: httpx.Response(429, json={"errors": [{"message": "limit"}]}))

    with pytest.raises(Bildfehler, match="Mitternacht"):
        g.erzeuge("x", tmp_path / "b.png")


def test_beide_neuen_wege_stehen_zur_auswahl():
    from insta_agent.imaging.generator import ANBIETER, OHNE_SCHLUESSEL

    assert "pollinations" in ANBIETER
    assert "cloudflare" in ANBIETER
    # Pollinations braucht nicht einmal ein Konto.
    assert "pollinations" in OHNE_SCHLUESSEL
    assert "cloudflare" not in OHNE_SCHLUESSEL


# --- Das Akzentwort --------------------------------------------------------
#
# Eine Schlagzeile unterscheidet sich von einer Bildunterschrift dadurch,
# dass ein Wort heraussticht: die Zahl, die Tiefe, der Name. Genau das
# macht den Unterschied zwischen "da steht Text auf einem Bild" und
# "da ist eine Aussage".


def _akzentanteil(bild_pfad, akzent=(123, 224, 90)) -> int:
    """Wie viele Pixel in der ersten Textzeile die Akzentfarbe tragen."""
    from PIL import Image

    bild = Image.open(bild_pfad).convert("RGB")
    oben = int(bild.height * 0.15)
    streifen = bild.crop((0, oben, bild.width, oben + int(bild.height * 0.04)))
    return sum(
        1
        for p in streifen.getdata()
        if abs(p[0] - akzent[0]) < 30 and abs(p[1] - akzent[1]) < 30 and abs(p[2] - akzent[2]) < 30
    )


def _grund(pfad, groesse):
    from PIL import Image

    Image.new("RGB", groesse, (8, 26, 38)).save(pfad)
    return pfad


def test_das_akzentwort_steht_in_der_akzentfarbe(tmp_path):
    from insta_agent.imaging import STORY, lege_hook_auf
    from insta_agent.models import VisualSpec

    spec = VisualSpec(
        headline="7.902 Meter tief. Und es wartet.",
        akzentwort="7.902 Meter",
        text_hex="#FFFFFF",
        accent_hex="#7BE05A",
    )
    ziel = lege_hook_auf(
        _grund(tmp_path / "g.png", STORY), tmp_path / "a.png", text=spec.headline, spec=spec
    )

    assert _akzentanteil(ziel) > 200


def test_ohne_akzentwort_und_ohne_zahl_bleibt_alles_einfarbig(tmp_path):
    """Lieber gar kein Akzent als einer auf dem falschen Wort."""
    from insta_agent.imaging import STORY, lege_hook_auf
    from insta_agent.models import VisualSpec

    spec = VisualSpec(
        headline="Ein Satz ganz ohne jede Ziffer darin",
        text_hex="#FFFFFF",
        accent_hex="#7BE05A",
    )
    ziel = lege_hook_auf(
        _grund(tmp_path / "g.png", STORY), tmp_path / "b.png", text=spec.headline, spec=spec
    )

    assert _akzentanteil(ziel) == 0


def test_ohne_angabe_wird_die_zahl_hervorgehoben(tmp_path):
    """In diesen Beiträgen ist fast immer die Zahl das, was zählt."""
    from insta_agent.imaging import STORY, lege_hook_auf
    from insta_agent.models import VisualSpec

    spec = VisualSpec(
        headline="7.902 Meter tief. Und es wartet.", text_hex="#FFFFFF", accent_hex="#7BE05A"
    )
    ziel = lege_hook_auf(
        _grund(tmp_path / "g.png", STORY), tmp_path / "c.png", text=spec.headline, spec=spec
    )

    assert _akzentanteil(ziel) > 200


def test_ein_akzentwort_das_gar_nicht_dasteht_faellt_zurueck():
    """Sonst wäre die Hervorhebung spurlos verloren."""
    from insta_agent.imaging.renderer import _akzentkerne
    from insta_agent.models import VisualSpec

    spec = VisualSpec(headline="x", akzentwort="Rübenacker")

    assert _akzentkerne(spec, "7.902 Meter tief") == {"7.902"}


def test_satzzeichen_stehen_der_hervorhebung_nicht_im_weg():
    from insta_agent.imaging.renderer import _akzentkerne
    from insta_agent.models import VisualSpec

    spec = VisualSpec(headline="x", akzentwort="Tiefsee")

    assert _akzentkerne(spec, "Die Tiefsee, dunkel und still") == {"tiefsee"}


def test_die_notfassung_hebt_dasselbe_wort_hervor(tmp_path):
    """Beide Wege müssen gleich aussehen, sonst fällt einer aus der Reihe."""
    from insta_agent.imaging import STORY, render_post_image
    from insta_agent.models import VisualSpec

    spec = VisualSpec(
        headline="7.902 Meter tief. Und es wartet.",
        akzentwort="7.902 Meter",
        background_hex="#061822",
        text_hex="#FFFFFF",
        accent_hex="#7BE05A",
    )
    ziel = render_post_image(spec, tmp_path / "d.png", groesse=STORY)

    from PIL import Image

    bild = Image.open(ziel).convert("RGB")
    treffer = sum(
        1
        for p in bild.getdata()
        if abs(p[0] - 123) < 30 and abs(p[1] - 224) < 30 and abs(p[2] - 90) < 30
    )
    # Der Akzentbalken oben allein macht rund 19.000 Pixel aus.
    assert treffer > 25000


def test_die_schrift_bekommt_eine_kontur(tmp_path):
    """Auf einem hellen Fleck mitten im Wort trägt kein Verlauf mehr."""
    from PIL import Image

    from insta_agent.imaging import STORY, lege_hook_auf
    from insta_agent.models import VisualSpec

    hell = tmp_path / "hell.png"
    Image.new("RGB", STORY, (235, 240, 245)).save(hell)
    spec = VisualSpec(headline="Weiss auf Weiss", text_hex="#FFFFFF", accent_hex="#7BE05A")

    ziel = lege_hook_auf(hell, tmp_path / "e.png", text=spec.headline, spec=spec)

    bild = Image.open(ziel).convert("RGB")
    oben = int(bild.height * 0.15)
    streifen = bild.crop((0, oben, bild.width, oben + int(bild.height * 0.05)))
    # Ohne Kontur gäbe es hier gar keine dunklen Pixel.
    assert sum(1 for p in streifen.getdata() if sum(p) < 200) > 500
