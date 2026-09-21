"""Der eigene Rechner als Bilddienst.

Der einzige wirklich kostenlose Weg - und der einzige, bei dem man sich
das Modell selbst aussucht. Zwei Dinge gehen dabei schief, wenn man sie
nicht behandelt:

Erstens weiss niemand, ob das Bildprogramm wirklich läuft, bis der erste
Beitrag ansteht. Dann sieht es aus, als läge es am Agenten.

Zweitens brauchen FLUX und SDXL verschiedene Einstellungen. Wer FLUX mit
den SDXL-Werten fährt - CFG 5 statt 1 - bekommt verbrannte, überzeichnete
Bilder und sucht den Fehler im Prompt.
"""

from __future__ import annotations

import httpx
import pytest

from insta_agent.imaging.generator import (
    Bildfehler,
    LokalerGenerator,
    frage_lokal_ab,
    ist_flux,
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


def test_ohne_modellangabe_gelten_die_sdxl_werte():
    """Die verbreitetere Sorte - und die gutmuetigere von beiden."""
    assert werte_fuer("")["cfg_scale"] == 5.0


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
