"""Vier Schriftfamilien, damit nicht jeder Beitrag gleich aussieht."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from insta_agent.imaging.overlay import lege_hook_auf
from insta_agent.imaging.renderer import (
    SCHRIFTEN,
    _load_font,
    render_post_image,
    schriftdatei,
)
from insta_agent.models import VisualSpec


def _spec(**felder) -> VisualSpec:
    return VisualSpec(headline="Zwölf Meter unter einem Rübenacker", **felder)


def test_jede_familie_hat_hier_eine_eigene_datei():
    """Auf dem Prüfrechner: Grotesk, Serife und Mono sind verschiedene Dateien."""
    klar, ernst, technisch = (schriftdatei(f) for f in ("klar", "ernst", "technisch"))
    assert klar and ernst and technisch
    assert len({klar, ernst, technisch}) == 3
    assert "Serif" in ernst
    assert "Mono" in technisch


def test_unbekannte_familie_faellt_auf_klar_zurueck():
    assert schriftdatei("gibtsnicht") == schriftdatei("klar")
    assert _load_font(40, familie="gibtsnicht").path == _load_font(40, familie="klar").path


def test_wucht_faellt_ohne_arial_black_auf_die_grotesk_zurueck():
    """Auf Linux gibt es keine Arial Black - dann eben fett gesetzt, nicht kaputt."""
    assert _load_font(40, familie="wucht").path.endswith(("Bold.ttf", ".ttc"))


def test_jede_familie_kennt_windows_und_linux():
    for name, reihe in SCHRIFTEN.items():
        for art in ("fett", "normal"):
            assert any(p.startswith("C:/Windows") for p in reihe[art]), (name, art)
            assert any(p.startswith("/usr/share") for p in reihe[art]), (name, art)


def test_die_typografische_fassung_nimmt_die_gewaehlte_schrift(tmp_path, monkeypatch):
    import insta_agent.imaging.renderer as r

    benutzt = []
    echte = r._load_font
    monkeypatch.setattr(r, "_load_font", lambda *a, **k: (benutzt.append(k.get("familie")), echte(*a, **k))[1])

    render_post_image(_spec(schrift="ernst"), tmp_path / "ernst.png")

    assert benutzt and set(benutzt) == {"ernst"}


def test_der_hook_auf_dem_foto_nimmt_die_gewaehlte_schrift(tmp_path, monkeypatch):
    import insta_agent.imaging.renderer as r

    benutzt = []
    echte = r._load_font
    monkeypatch.setattr(r, "_load_font", lambda *a, **k: (benutzt.append(k.get("familie")), echte(*a, **k))[1])
    foto = tmp_path / "foto.jpg"
    Image.new("RGB", (1080, 1350), (20, 30, 40)).save(foto)

    lege_hook_auf(foto, tmp_path / "fertig.png", text="Zwölf Meter", spec=_spec(schrift="technisch"), groesse=(1080, 1350))

    assert benutzt and set(benutzt) == {"technisch"}


def test_zwei_familien_ergeben_verschiedene_bilder(tmp_path):
    a = render_post_image(_spec(schrift="klar"), tmp_path / "a.png")
    b = render_post_image(_spec(schrift="ernst"), tmp_path / "b.png")
    assert Path(a).read_bytes() != Path(b).read_bytes()


def test_alte_entwuerfe_ohne_schrift_bleiben_lesbar():
    spec = VisualSpec.model_validate({"headline": "x"})
    assert spec.schrift == "klar"
