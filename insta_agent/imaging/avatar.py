"""Ein Portrait für den Agenten - gezeichnet, nicht fotografiert.

Bewusst eine Grafik und kein Foto: Der Agent betreibt einen Account, den
später fremde Menschen sehen. Ein fotorealistisches Gesicht einer Person,
die es nicht gibt, würde diese Menschen glauben lassen, dort sitze ein
Mensch. Ein gezeichnetes Zeichen sagt dasselbe über ihn aus, ohne jemanden
zu täuschen.

Das Bild entsteht aus seinem Namen: Gleicher Name, gleiches Portrait - und
zwei verschiedene Agenten sehen nie gleich aus.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from PIL import Image, ImageDraw

from .renderer import _ensure_readable, _hex_to_rgb, _load_font

GROESSE = 512


def _initialen(name: str) -> str:
    teile = [t for t in name.replace("-", " ").split() if t]
    if not teile:
        return "?"
    if len(teile) == 1:
        return teile[0][:2].upper()
    return (teile[0][0] + teile[-1][0]).upper()


def _mischen(a: tuple[int, int, int], b: tuple[int, int, int], anteil: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * anteil) for x, y in zip(a, b))  # type: ignore[return-value]


def render_avatar(
    name: str,
    out_path: Path,
    *,
    background_hex: str = "#111318",
    accent_hex: str = "#E4572E",
) -> Path:
    """Zeichnet ein Portrait aus Name und Farben des Agenten.

    Die Farben stammen aus seinem letzten Beitrag - das ist die
    Bildsprache, die er tatsächlich verwendet, nicht die, die er
    beschrieben hat.
    """
    name = name or "Agent"
    hintergrund = _hex_to_rgb(background_hex, (17, 19, 24))
    akzent = _hex_to_rgb(accent_hex, (228, 87, 46))

    bild = Image.new("RGB", (GROESSE, GROESSE), hintergrund)
    zeichner = ImageDraw.Draw(bild)

    # Aus dem Namen abgeleitet: gleicher Name, gleiches Bild.
    saat = hashlib.sha256(name.encode("utf-8")).digest()

    # Weiche Ringe im Hintergrund, Lage und Größe aus der Saat.
    for i in range(5):
        anteil = 0.06 + i * 0.045
        farbe = _mischen(hintergrund, akzent, anteil)
        radius = GROESSE * (0.30 + (saat[i] / 255) * 0.42)
        mitte_x = GROESSE * (0.25 + (saat[i + 5] / 255) * 0.5)
        mitte_y = GROESSE * (0.25 + (saat[i + 10] / 255) * 0.5)
        zeichner.ellipse(
            [mitte_x - radius, mitte_y - radius, mitte_x + radius, mitte_y + radius],
            fill=farbe,
        )

    # Ein Kreisbogen als Rahmen - der Anfangswinkel kommt ebenfalls aus dem Namen.
    rand = GROESSE * 0.055
    start = (saat[15] / 255) * 360
    zeichner.arc(
        [rand, rand, GROESSE - rand, GROESSE - rand],
        start=start,
        end=start + 250,
        fill=akzent,
        width=int(GROESSE * 0.025),
    )

    initialen = _initialen(name)
    schrift = _load_font(int(GROESSE * 0.36), bold=True)
    textfarbe = _ensure_readable((245, 245, 240), _mischen(hintergrund, akzent, 0.2))

    kasten = zeichner.textbbox((0, 0), initialen, font=schrift)
    zeichner.text(
        ((GROESSE - (kasten[2] - kasten[0])) / 2 - kasten[0],
         (GROESSE - (kasten[3] - kasten[1])) / 2 - kasten[1]),
        initialen,
        font=schrift,
        fill=textfarbe,
    )

    # Rund zuschneiden, damit es als Profilbild taugt.
    maske = Image.new("L", (GROESSE, GROESSE), 0)
    ImageDraw.Draw(maske).ellipse([0, 0, GROESSE, GROESSE], fill=255)
    rund = Image.new("RGBA", (GROESSE, GROESSE), (0, 0, 0, 0))
    rund.paste(bild, (0, 0), maske)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rund.save(out_path, "PNG")
    return out_path
