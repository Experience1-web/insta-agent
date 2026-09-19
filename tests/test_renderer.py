"""Das Bild muss immer lesbar herauskommen - auch bei schlechten Vorgaben."""

from PIL import Image

from insta_agent.imaging.renderer import (
    HEIGHT,
    WIDTH,
    _contrast_ratio,
    _ensure_readable,
    _hex_to_rgb,
    render_post_image,
)
from insta_agent.models import VisualSpec


def test_bild_hat_das_erwartete_format(tmp_path, draft):
    path = render_post_image(draft.visual, tmp_path / "post.png")
    with Image.open(path) as image:
        assert image.size == (WIDTH, HEIGHT)


def test_schlechter_kontrast_wird_korrigiert():
    """Weiß auf Creme wäre unlesbar - der Renderer muss eingreifen."""
    background = (245, 240, 232)
    fixed = _ensure_readable((248, 248, 248), background)
    assert _contrast_ratio(fixed, background) >= 4.5


def test_guter_kontrast_bleibt_unangetastet():
    background = (17, 19, 24)
    wanted = (245, 245, 240)
    assert _ensure_readable(wanted, background) == wanted


def test_kaputte_farbangabe_faellt_auf_den_standard_zurueck():
    fallback = (1, 2, 3)
    assert _hex_to_rgb("keine-farbe", fallback) == fallback
    assert _hex_to_rgb("", fallback) == fallback
    assert _hex_to_rgb("#ZZZZZZ", fallback) == fallback
    # Kurzschreibweise muss funktionieren
    assert _hex_to_rgb("#fff", fallback) == (255, 255, 255)


def test_sehr_lange_headline_sprengt_das_bild_nicht(tmp_path):
    spec = VisualSpec(
        headline="Ein außergewöhnlich langer Satz über Beständigkeit, "
        "Disziplin und die Kunst, trotzdem weiterzumachen, wenn niemand zusieht",
        body_lines=["Zeile eins", "Zeile zwei", "Zeile drei", "Zeile vier", "Zeile fünf"],
        subline="Und dazu noch eine Unterzeile, die ebenfalls recht lang ausfällt",
    )
    path = render_post_image(spec, tmp_path / "lang.png")
    with Image.open(path) as image:
        assert image.size == (WIDTH, HEIGHT)


def test_ein_einzelnes_wort_funktioniert(tmp_path):
    path = render_post_image(VisualSpec(headline="Durchhalten"), tmp_path / "kurz.png")
    assert path.exists()
