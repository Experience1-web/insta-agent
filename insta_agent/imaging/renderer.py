"""Bilder rein typografisch erzeugen - lokal, ohne Kosten.

Der Agent hat kein Fotostudio und kein Bildmodell. Er hat Farbe, Schrift
und einen Satz, der sitzt. Das reicht für Zitatkacheln, Zahlenkarten und
Listen - genau die Formate, die auf Instagram geteilt werden.

Porträt 1080x1350 ist bewusst gewählt: es nimmt im Feed mehr Höhe ein
als ein Quadrat und wird dadurch länger gesehen.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..models import VisualSpec

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1350
MARGIN = 96

# Reihenfolge nach Präferenz; die erste vorhandene Schrift gewinnt.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",
]


def _load_font(size: int, *, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = FONT_CANDIDATES if bold else FONT_CANDIDATES_REGULAR
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    # Ohne TrueType-Schrift bleibt nur die Bitmap-Schrift; das Bild wird
    # hässlich, aber der Zyklus bricht nicht ab.
    log.warning("Keine TrueType-Schrift gefunden, nutze Notfallschrift")
    return ImageFont.load_default()


def _hex_to_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6:
        return fallback
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return fallback


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _ensure_readable(
    text: tuple[int, int, int], background: tuple[int, int, int]
) -> tuple[int, int, int]:
    """Erzwingt lesbaren Kontrast, auch wenn das Modell schlecht wählt."""
    if _contrast_ratio(text, background) >= 4.5:
        return text
    white, black = (255, 255, 255), (17, 17, 17)
    return white if _contrast_ratio(white, background) >= _contrast_ratio(black, background) else black


def _wrap_to_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> list[str]:
    """Umbricht anhand der wirklich gemessenen Breite, nicht nach Zeichenzahl.

    Eine feste Zeichenzahl geht bei breiten Wörtern schief - die Zeile läuft
    dann aus dem Bild. Deshalb wird hier Wort für Wort gemessen.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _ellipsize(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> str:
    """Kürzt eine Zeile auf die verfügbare Breite und hängt Auslassungspunkte an."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    cut = text
    while cut and draw.textlength(cut + "\u2026", font=font) > max_width:
        cut = cut[:-1]
    return cut.rstrip() + "\u2026"


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    *,
    start_size: int,
    min_size: int,
    bold: bool = True,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Verkleinert die Schrift so lange, bis der Text in den Kasten passt."""
    for size in range(start_size, min_size - 1, -4):
        font = _load_font(size, bold=bold)
        lines = _wrap_to_width(draw, text, font, max_width) or [text]
        line_height = int(size * 1.25)
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)
        if widest <= max_width and len(lines) * line_height <= max_height:
            return font, lines
    font = _load_font(min_size, bold=bold)
    return font, _wrap_to_width(draw, text, font, max_width) or [text]


def render_post_image(spec: VisualSpec, out_path: Path) -> Path:
    """Rendert den Bauplan zu einer fertigen PNG-Datei."""
    background = _hex_to_rgb(spec.background_hex, (17, 19, 24))
    text_color = _ensure_readable(_hex_to_rgb(spec.text_hex, (245, 245, 240)), background)
    accent = _hex_to_rgb(spec.accent_hex, (228, 87, 46))

    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)

    # Akzentbalken oben - gibt dem Feed einen Wiedererkennungswert.
    draw.rectangle([(0, 0), (WIDTH, 18)], fill=accent)

    inner_width = WIDTH - 2 * MARGIN
    body_lines = [line for line in spec.body_lines if line.strip()][:5]

    # Jedes Element bekommt seinen eigenen Höhenanteil, damit die Headline
    # den Rest nicht erdrückt.
    reserved = 120  # Akzentbalken und Fußzeile
    reserved += len(body_lines) * 64 + (40 if body_lines else 0)
    reserved += 120 if spec.subline.strip() else 0
    headline_budget = max(HEIGHT - 2 * MARGIN - reserved, 240)

    # Kurze Sätze dürfen groß werden, lange fangen kleiner an - sonst
    # zerfällt die Headline in sieben Zeilen.
    start_size = 112 if len(spec.headline) <= 34 else 92 if len(spec.headline) <= 60 else 76
    font, lines = _fit_text(
        draw,
        spec.headline,
        inner_width,
        headline_budget,
        start_size=start_size,
        min_size=40,
    )

    line_height = int(font.size * 1.25) if hasattr(font, "size") else 40
    block_height = len(lines) * line_height
    y = max(MARGIN + 60, (HEIGHT - block_height) // 2 - (len(body_lines) * 34))

    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=text_color)
        y += line_height

    if spec.subline.strip():
        sub_font = _load_font(max(int(getattr(font, "size", 60) * 0.42), 28), bold=False)
        y += 16
        for line in _wrap_to_width(draw, spec.subline, sub_font, inner_width)[:3]:
            draw.text((MARGIN, y), line, font=sub_font, fill=accent)
            y += int(sub_font.size * 1.3)

    if body_lines:
        body_font = _load_font(38, bold=False)
        y += 36
        for line in body_lines:
            draw.ellipse([(MARGIN, y + 14), (MARGIN + 14, y + 28)], fill=accent)
            clipped = _ellipsize(draw, line, body_font, inner_width - 36)
            draw.text((MARGIN + 36, y), clipped, font=body_font, fill=text_color)
            y += 64

    if spec.footer.strip():
        footer_font = _load_font(30, bold=False)
        draw.text((MARGIN, HEIGHT - MARGIN), spec.footer, font=footer_font, fill=accent, anchor="ls")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", optimize=True)
    return out_path
