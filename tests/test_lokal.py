"""Der eigene Rechner als Bilddienst.

Der einzige wirklich kostenlose Weg - und der einzige, bei dem man sich
das Modell selbst aussucht. Zwei Dinge gehen dabei schief, wenn man sie
nicht behandelt:

Erstens weiss niemand, ob das Bildprogramm wirklich läuft, bis der erste
Beitrag ansteht. Dann sieht es aus, als läge es am Agenten.

Zweitens brauchen FLUX, SDXL und SD 1.5 verschiedene Einstellungen. Wer
FLUX mit den SDXL-Werten fährt - CFG 5 statt 1 - bekommt verbrannte,
überzeichnete Bilder und sucht den Fehler im Prompt. Und wer SD 1.5 auf
SDXL-Maßen malen lässt, bekommt doppelte Köpfe.
"""

from __future__ import annotations

import httpx
import pytest

from insta_agent.imaging.generator import (
    GRUNDMASSE,
    Bildfehler,
    LokalerGenerator,
    frage_lokal_ab,
    ist_flux,
    modellart,
    werte_fuer,
)


# --- FLUX oder SDXL --------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["flux1-dev-Q4_K_M.gguf", "FLUX.1-schnell", "flux1-dev-fp8.safetensors", "myFLUXmix"],
)
def test_flux_wird_erkannt(name):
    assert ist_flux(name)


@pytest.mark.parametrize(
    "name",
    ["juggernautXL_v10.safetensors", "RealVisXL_V5.0.safetensors", "sd_xl_base_1.0", ""],
)
def test_sdxl_wird_nicht_fuer_flux_gehalten(name):
    assert not ist_flux(name)


def test_flux_bekommt_cfg_eins():
    """Mit CFG 5 liefert FLUX verbrannte Bilder - das ist der teuerste
    Einstellungsfehler auf dem eigenen Rechner."""
    werte = werte_fuer("flux1-dev-Q4_K_M.gguf")

    assert werte["cfg_scale"] == 1.0
    # FLUX kennt keine klassische Negativfuehrung.
    assert werte["negative_prompt"] == ""


def test_sdxl_behaelt_negativfuehrung_und_hoeheres_cfg():
    werte = werte_fuer("juggernautXL_v10.safetensors")

    assert werte["cfg_scale"] == 5.0
    assert "watermark" in werte["negative_prompt"]


def test_ohne_modellangabe_gilt_sd_15():
    """Im Zweifel die vorsichtigere Annahme.

    Ein SDXL-Modell auf SD-1.5-Massen wird etwas flau. Ein SD-1.5-Modell
    auf SDXL-Massen bekommt doppelte Koepfe. Also raten wir nach unten.
    """
    assert werte_fuer("")["cfg_scale"] == 7.0
    assert werte_fuer("")["enable_hr"] is True


def test_die_werte_landen_wirklich_in_der_anfrage(tmp_path):
    import base64

    gesehen: dict = {}

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        import json

        gesehen.update(json.loads(anfrage.content))
        winziges_png = base64.b64encode(b"\\x89PNG\\r\\n\\x1a\\n").decode()
        return httpx.Response(200, json={"images": [winziges_png]})

    gen = LokalerGenerator("http://127.0.0.1:7860", "flux1-dev.gguf")
    gen.client = httpx.Client(transport=httpx.MockTransport(antworte))
    try:
        gen.erzeuge("ein Motiv", tmp_path / "x.png")
    finally:
        gen.close()

    assert gesehen["cfg_scale"] == 1.0
    assert gesehen["steps"] == 20
    # Das Seitenverhaeltnis bleibt, unabhaengig vom Modell.
    assert gesehen["width"] == 792 and gesehen["height"] == 1408


# --- Die Probe beim Einrichten ---------------------------------------------


def test_die_probe_nennt_die_gefundenen_modelle():
    def antworte(anfrage: httpx.Request) -> httpx.Response:
        if "sd-models" in anfrage.url.path:
            return httpx.Response(
                200,
                json=[
                    {"model_name": "juggernautXL_v10", "title": "juggernautXL_v10 [abc]"},
                    {"model_name": "flux1-dev-Q4_K_M", "title": "flux1 [def]"},
                ],
            )
        return httpx.Response(200, json={"sd_model_checkpoint": "juggernautXL_v10 [abc]"})

    import insta_agent.imaging.generator as g

    echter = httpx.Client
    g.httpx.Client = lambda *a, **k: echter(*a, **{**k, "transport": httpx.MockTransport(antworte)})
    try:
        modelle, geladen, _ = frage_lokal_ab("http://127.0.0.1:7860")
    finally:
        g.httpx.Client = echter

    assert modelle == ["juggernautXL_v10", "flux1-dev-Q4_K_M"]
    assert "juggernautXL" in geladen


def test_ein_totes_bildprogramm_wird_klar_benannt():
    import insta_agent.imaging.generator as g

    def tot(anfrage: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nichts da")

    echter = httpx.Client
    g.httpx.Client = lambda *a, **k: echter(*a, **{**k, "transport": httpx.MockTransport(tot)})
    try:
        with pytest.raises(Bildfehler) as fehler:
            frage_lokal_ab("http://127.0.0.1:7860")
    finally:
        g.httpx.Client = echter

    assert "--api" in str(fehler.value)


def test_ohne_api_schalter_steht_das_auch_da():
    import insta_agent.imaging.generator as g

    echter = httpx.Client
    g.httpx.Client = lambda *a, **k: echter(
        *a, **{**k, "transport": httpx.MockTransport(lambda r: httpx.Response(404))}
    )
    try:
        with pytest.raises(Bildfehler) as fehler:
            frage_lokal_ab("http://127.0.0.1:7860")
    finally:
        g.httpx.Client = echter

    assert "--api" in str(fehler.value)


# --- Grafikkarte oder Prozessor --------------------------------------------
#
# Der teuerste stille Fehler beim eigenen Rechner: PyTorch in der
# Prozessorfassung. Es laeuft alles - nur dauert ein Bild zwanzig Minuten
# statt einer. Im Protokoll steht es als beilaeufige Warnung zwischen
# hundert anderen Zeilen.


def _mit_speicherauskunft(antwort_auf_memory):
    import insta_agent.imaging.generator as g

    def antworte(anfrage):
        pfad = anfrage.url.path
        if "sd-models" in pfad:
            return httpx.Response(200, json=[{"model_name": "sdxl", "title": "sdxl"}])
        if "memory" in pfad:
            return antwort_auf_memory
        return httpx.Response(200, json={"sd_model_checkpoint": "sdxl"})

    echter = httpx.Client
    g.httpx.Client = lambda *a, **k: echter(
        *a, **{**k, "transport": httpx.MockTransport(antworte)}
    )
    return g, echter


def test_eine_fehlende_grafikkarte_wird_erkannt():
    """Genau der Fall, der im Betrieb auftrat."""
    g, echter = _mit_speicherauskunft(
        httpx.Response(200, json={"cuda": {"error": "torch.cuda is not available"}})
    )
    try:
        _, _, auf_karte = frage_lokal_ab("http://127.0.0.1:7860")
    finally:
        g.httpx.Client = echter

    assert auf_karte is False


def test_eine_vorhandene_grafikkarte_auch():
    g, echter = _mit_speicherauskunft(
        httpx.Response(200, json={"cuda": {"system": {"free": 1, "total": 8}}})
    )
    try:
        _, _, auf_karte = frage_lokal_ab("http://127.0.0.1:7860")
    finally:
        g.httpx.Client = echter

    assert auf_karte is True


def test_aeltere_fassungen_kennen_die_auskunft_nicht():
    """Dann wird nichts behauptet - None heisst nicht feststellbar."""
    g, echter = _mit_speicherauskunft(httpx.Response(404))
    try:
        _, _, auf_karte = frage_lokal_ab("http://127.0.0.1:7860")
    finally:
        g.httpx.Client = echter

    assert auf_karte is None


# --- SD 1.5: die kleine Welt -----------------------------------------------


@pytest.mark.parametrize(
    "name, erwartet",
    [
        ("juggernautXL_ragnarok", "sdxl"),
        ("sd_xl_base_1.0", "sdxl"),
        ("Juggernaut-XL-v9", "sdxl"),
        ("ponyDiffusionV6", "sdxl"),
        ("realisticVisionV60B1_v51HyperVAE", "sd15"),
        ("epicrealism_naturalSinRC1VAE", "sd15"),
        ("v1-5-pruned-emaonly", "sd15"),
        ("dreamshaper_8", "sd15"),
        ("flux1-dev-Q4_K_S", "flux"),
        ("", "sd15"),
    ],
)
def test_die_bauart_wird_am_namen_erkannt(name, erwartet):
    assert modellart(name) == erwartet


def test_sd15_malt_klein_und_rechnet_danach_hoch():
    """512x768 ist die Flaeche, auf die SD 1.5 trainiert wurde.

    Gross genug fuer Instagram ist das nicht - deshalb rechnet das
    Bildprogramm im zweiten Durchgang selbst hoch. Andersherum, gleich
    gross malen zu lassen, zerstoert die Bildkomposition.
    """
    assert GRUNDMASSE["sd15"] == (512, 768)
    werte = werte_fuer("realisticVisionV60B1")
    assert werte["enable_hr"] is True
    assert werte["hr_scale"] == 2.0
    # Ohne echte Negativfuehrung sieht man SD 1.5 sein Alter an.
    assert "bad anatomy" in werte["negative_prompt"]


def test_die_eingestellte_bauart_schlaegt_den_namen():
    """Die Erkennung am Namen kann danebenliegen - dann zaehlt die Angabe."""
    gen = LokalerGenerator("http://x", "mein_lieblingsmodell", art="sdxl")
    assert gen.bauart == "sdxl"
    # Unsinn wird ignoriert, statt den Zyklus umzuwerfen.
    assert LokalerGenerator("http://x", "flux1-dev", art="quatsch").bauart == "flux"


def test_reicht_der_grafikspeicher_nicht_faellt_nur_das_hochrechnen_weg(tmp_path):
    """Ein kleineres Bild ist besser als kein Bild.

    Auf einer 4-GB-Karte sprengt der zweite Durchgang regelmaessig den
    Speicher. Den ganzen Beitrag daran scheitern zu lassen, waere die
    teuerste aller Reaktionen.
    """
    import base64
    import json

    anfragen: list[dict] = []
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        koerper = json.loads(anfrage.content)
        anfragen.append(koerper)
        if koerper.get("enable_hr"):
            return httpx.Response(500, json={"detail": "CUDA out of memory"})
        return httpx.Response(200, json={"images": [png]})

    gen = LokalerGenerator("http://lokal", "realisticVision", timeout=5.0)
    gen.client = httpx.Client(transport=httpx.MockTransport(antworte), timeout=5.0)
    gen.erzeuge("ein Fisch", tmp_path / "b.png")

    assert len(anfragen) == 2
    assert anfragen[0]["enable_hr"] is True
    assert "enable_hr" not in anfragen[1]
    assert (tmp_path / "b.png").exists()


def test_ein_unbekannter_sampler_wird_einmal_ohne_karras_versucht(tmp_path):
    """Aeltere und neuere Fassungen benennen den Sampler verschieden."""
    import base64
    import json

    anfragen: list[dict] = []
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        koerper = json.loads(anfrage.content)
        anfragen.append(koerper)
        if "Karras" in str(koerper.get("sampler_name")):
            return httpx.Response(404, json={"detail": "Sampler not found"})
        return httpx.Response(200, json={"images": [png]})

    gen = LokalerGenerator("http://lokal", "realisticVision", timeout=5.0)
    gen.client = httpx.Client(transport=httpx.MockTransport(antworte), timeout=5.0)
    gen.erzeuge("ein Fisch", tmp_path / "b.png")

    assert [a["sampler_name"] for a in anfragen] == ["DPM++ 2M Karras", "DPM++ 2M"]


def test_ein_echter_fehler_wird_nicht_endlos_wiederholt(tmp_path):
    """Nur die zwei bekannten Stolpersteine bekommen einen zweiten Versuch."""
    import json

    anfragen: list[dict] = []

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        anfragen.append(json.loads(anfrage.content))
        return httpx.Response(500, json={"detail": "irgendwas ganz anderes"})

    gen = LokalerGenerator("http://lokal", "realisticVision", timeout=5.0)
    gen.client = httpx.Client(transport=httpx.MockTransport(antworte), timeout=5.0)
    with pytest.raises(Bildfehler):
        gen.erzeuge("ein Fisch", tmp_path / "b.png")

    assert len(anfragen) == 1


def test_jeder_eingetragene_anbieter_laesst_sich_bauen():
    """Der Test, der gefehlt hat.

    Die Bauart wurde an alle schluessellosen Anbieter weitergereicht,
    obwohl nur der eigene Rechner sie kennt - und Pollinations ist beim
    Bauen abgestuerzt, bevor ueberhaupt ein Bild angefragt wurde. Kein
    einziger Test hatte je einen anderen Anbieter als den lokalen gebaut.
    """
    from insta_agent.imaging.generator import ANBIETER, baue_generator

    for name in ANBIETER:
        gen = baue_generator(name, "irgendein-zugang", "", art="sd15")
        assert gen is not None, name
        if hasattr(gen, "close"):
            gen.close()
