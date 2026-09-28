"""Bilder rein typografisch erzeugen - lokal, ohne Kosten.

Der Agent hat kein Fotostudio und kein Bildmodell. Er hat Farbe, Schrift
und einen Satz, der sitzt. Das reicht für Zitatkacheln, Zahlenkarten und
Listen - genau die Formate, die auf Instagram geteilt werden.

Zwei Formate:

- FEED (1080x1350) für den normalen Beitrag. Nimmt mehr Höhe ein als ein
  Quadrat und wird dadurch länger gesehen.
- STORY (1080x1920) im Verhältnis 9:16, für Reels und Stories. Hier steht
  der Hook allein und bildschirmfüllend - das ist das Format, in dem der
  Daumen entscheidet.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..models import VisualSpec

log = logging.getLogger(__name__)

FEED = (1080, 1350)
STORY = (1080, 1920)  # 9:16

WIDTH, HEIGHT = FEED  # Voreinstellung, für Aufrufer ohne Formatwunsch
MARGIN = 96

# Vier Schriftfamilien, damit nicht jeder Beitrag gleich aussieht. Der
# Agent waehlt eine je Beitrag (`VisualSpec.schrift`), alle Karten eines
# Karussells tragen dieselbe. Je Familie eine Reihe nach Praeferenz; die
# erste vorhandene Datei gewinnt. Windows, Mac und Linux stehen nebeneinander,
# weil das Programm beim Betreiber auf Windows laeuft und hier auf Linux
# geprueft wird - die Bilder sollen auf beiden gleich gut aussehen.
SCHRIFTEN: dict[str, dict[str, list[str]]] = {
    # Klar und neutral - die Grotesk, mit der alles begann.
    "klar": {
        "fett": [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ],
        "normal": [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ],
    },
    # Ernst, mit Serifen - fuer Geschichte, Grabungen, alte Dinge.
    "ernst": {
        "fett": [
            "C:/Windows/Fonts/georgiab.ttf",
            "C:/Windows/Fonts/timesbd.ttf",
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        ],
        "normal": [
            "C:/Windows/Fonts/georgia.ttf",
            "C:/Windows/Fonts/times.ttf",
            "/System/Library/Fonts/Supplemental/Georgia.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        ],
    },
    # Wuchtig, sehr fett - fuer grosse Zahlen und laute Saetze.
    "wucht": {
        "fett": [
            "C:/Windows/Fonts/ariblk.ttf",
            "C:/Windows/Fonts/verdanab.ttf",
            "/System/Library/Fonts/Supplemental/Arial Black.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ],
        "normal": [
            "C:/Windows/Fonts/verdana.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ],
    },
    # Technisch, gleich breite Zeichen - fuer Weltall, Geraete, Messwerte.
    "technisch": {
        "fett": [
            "C:/Windows/Fonts/consolab.ttf",
            "C:/Windows/Fonts/lucon.ttf",
            "/System/Library/Fonts/Menlo.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        ],
        "normal": [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/lucon.ttf",
            "/System/Library/Fonts/Menlo.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ],
    },
}
STANDARDSCHRIFT = "klar"

# Die alten Namen bleiben fuer alles, was sie noch importiert.
FONT_CANDIDATES = SCHRIFTEN["klar"]["fett"]
FONT_CANDIDATES_REGULAR = SCHRIFTEN["klar"]["normal"]


def schriftdatei(familie: str, *, bold: bool = True) -> str | None:
    """Welche Datei fuer diese Familie hier vorhanden ist - oder None."""
    reihe = SCHRIFTEN.get(familie or STANDARDSCHRIFT, SCHRIFTEN[STANDARDSCHRIFT])
    for path in reihe["fett" if bold else "normal"]:
        if Path(path).exists():
            return path
    return None


def _load_font(
    size: int, *, bold: bool = True, familie: str = STANDARDSCHRIFT
) -> ImageFont.FreeTypeFont:
    # Erst die gewuenschte Familie, dann die Standardfamilie: Fehlt auf
    # einem Rechner die Serifenschrift, wird der Beitrag nicht haesslich,
    # sondern nur gewoehnlich.
    for name in dict.fromkeys([familie or STANDARDSCHRIFT, STANDARDSCHRIFT]):
        if (path := schriftdatei(name, bold=bold)) is not None:
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


# Wie dick die Kontur im Verhältnis zur Schriftgröße ist. Zu dünn trägt
# nicht, zu dick sieht nach Word-Art aus.
KONTUR = 0.055


def _wortkern(wort: str) -> str:
    """Ein Wort ohne Satzzeichen und Groß/Klein - zum Vergleichen."""
    return wort.strip(".,;:!?\"'\u201e\u201c\u2013-()").casefold()


def _akzentkerne(spec: VisualSpec, text: str) -> set[str]:
    """Welche Wörter farbig werden.

    Erste Wahl ist, was der Bauplan sagt. Sagt er nichts, wird die Zahl
    genommen: In diesen Beiträgen ist fast immer die Zahl das, was zählt -
    die Tiefe, das Alter, die Entfernung. Findet sich auch keine, bleibt
    alles einfarbig. Lieber gar kein Akzent als einer auf dem falschen Wort.
    """
    if gewuenscht := spec.akzentwort.strip():
        kerne = {_wortkern(w) for w in gewuenscht.split()}
        # Nur, was wirklich dasteht: Ein Akzentwort, das im Hook nicht
        # vorkommt, wäre sonst spurlos verloren.
        vorhanden = {_wortkern(w) for w in text.split()}
        if treffer := {k for k in kerne if k and k in vorhanden}:
            return treffer

    mit_ziffer = [
        _wortkern(w) for w in text.split() if any(z.isdigit() for z in w)
    ]
    return {k for k in mit_ziffer[:2] if k}


def _zeichne_zeile(
    zeichnung: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    zeile: str,
    *,
    schrift,
    textfarbe: tuple[int, int, int],
    akzent: tuple[int, int, int],
    kerne: set[str],
    kontur: int,
) -> None:
    """Malt eine Zeile Wort für Wort, damit einzelne Wörter farbig sein können.

    Das Leerzeichen wird mitgemessen und nicht mitgezeichnet - sonst
    wandern die Wörter bei jeder Schriftgröße anders auseinander.
    """
    x, y = xy
    leer = zeichnung.textlength(" ", font=schrift)
    for wort in zeile.split():
        farbe = akzent if _wortkern(wort) in kerne else textfarbe
        zeichnung.text(
            (x, y),
            wort,
            font=schrift,
            fill=farbe,
            stroke_width=kontur,
            stroke_fill=(0, 0, 0),
        )
        x += zeichnung.textlength(wort, font=schrift) + leer


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
    familie: str = STANDARDSCHRIFT,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Verkleinert die Schrift so lange, bis der Text in den Kasten passt."""
    for size in range(start_size, min_size - 1, -4):
        font = _load_font(size, bold=bold, familie=familie)
        lines = _wrap_to_width(draw, text, font, max_width) or [text]
        line_height = int(size * 1.25)
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)
        if widest <= max_width and len(lines) * line_height <= max_height:
            return font, lines
    font = _load_font(min_size, bold=bold, familie=familie)
    return font, _wrap_to_width(draw, text, font, max_width) or [text]


def render_post_image(
    spec: VisualSpec, out_path: Path, *, groesse: tuple[int, int] = FEED
) -> Path:
    """Rendert den Bauplan zu einer fertigen PNG-Datei.

    `groesse` ist FEED oder STORY. Im Story-Format bekommt die Headline
    mehr Höhe, weil sie dort allein wirken muss.
    """
    breite, hoehe = groesse
    background = _hex_to_rgb(spec.background_hex, (17, 19, 24))
    text_color = _ensure_readable(_hex_to_rgb(spec.text_hex, (245, 245, 240)), background)
    accent = _hex_to_rgb(spec.accent_hex, (228, 87, 46))

    image = Image.new("RGB", (breite, hoehe), background)
    draw = ImageDraw.Draw(image)

    # Akzentbalken oben - gibt dem Feed einen Wiedererkennungswert.
    draw.rectangle([(0, 0), (breite, 18)], fill=accent)

    inner_width = breite - 2 * MARGIN
    body_lines = [line for line in spec.body_lines if line.strip()][:5]

    # Jedes Element bekommt seinen eigenen Höhenanteil, damit die Headline
    # den Rest nicht erdrückt.
    reserved = 120  # Akzentbalken und Fußzeile
    reserved += len(body_lines) * 64 + (40 if body_lines else 0)
    reserved += 120 if spec.subline.strip() else 0
    headline_budget = max(hoehe - 2 * MARGIN - reserved, 240)

    # Kurze Sätze dürfen groß werden, lange fangen kleiner an - sonst
    # zerfällt die Headline in sieben Zeilen.
    start_size = 112 if len(spec.headline) <= 34 else 92 if len(spec.headline) <= 60 else 76
    # Im Hochformat ist mehr Platz - und der Hook soll ihn auch nutzen.
    if hoehe > breite * 1.5:
        start_size = int(start_size * 1.25)
    font, lines = _fit_text(
        draw,
        spec.headline,
        inner_width,
        headline_budget,
        start_size=start_size,
        min_size=40,
        familie=getattr(spec, "schrift", STANDARDSCHRIFT),
    )
    familie = getattr(spec, "schrift", STANDARDSCHRIFT)

    line_height = int(font.size * 1.25) if hasattr(font, "size") else 40
    block_height = len(lines) * line_height
    y = max(MARGIN + 60, (hoehe - block_height) // 2 - (len(body_lines) * 34))

    # Dieselbe Hervorhebung wie auf dem gemalten Bild: Beide Wege müssen
    # gleich aussehen, sonst fällt die Notfassung im Feed aus der Reihe.
    kerne = _akzentkerne(spec, spec.headline)
    for line in lines:
        _zeichne_zeile(
            draw,
            (MARGIN, y),
            line,
            schrift=font,
            textfarbe=text_color,
            akzent=accent,
            kerne=kerne,
            kontur=0,
        )
        y += line_height

    if spec.subline.strip():
        sub_font = _load_font(
            max(int(getattr(font, "size", 60) * 0.42), 28), bold=False, familie=familie
        )
        y += 16
        for line in _wrap_to_width(draw, spec.subline, sub_font, inner_width)[:3]:
            draw.text((MARGIN, y), line, font=sub_font, fill=accent)
            y += int(sub_font.size * 1.3)

    if body_lines:
        body_font = _load_font(38, bold=False, familie=familie)
        y += 36
        for line in body_lines:
            draw.ellipse([(MARGIN, y + 14), (MARGIN + 14, y + 28)], fill=accent)
            clipped = _ellipsize(draw, line, body_font, inner_width - 36)
            draw.text((MARGIN + 36, y), clipped, font=body_font, fill=text_color)
            y += 64

    if spec.footer.strip():
        footer_font = _load_font(30, bold=False, familie=familie)
        draw.text((MARGIN, hoehe - MARGIN), spec.footer, font=footer_font, fill=accent, anchor="ls")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", optimize=True)
    return out_path
