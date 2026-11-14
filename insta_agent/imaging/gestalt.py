"""Das Gestaltungssystem: wie ein Beitrag aussieht, wenn er wie ein Magazin aussehen soll.

Vorher gab es ein einziges Layout. Der Hook stand immer oben links auf
dem Foto, darunter ein kurzer Strich, alles in einem Grünblau - auf
jedem Bild, bei jedem Thema. Das sah nach Vorlage aus, und die Schrift
lag oft genau auf dem, was man sehen wollte.

Jetzt gilt, was gute Wissensmagazine tun:

- Zwei Schriften, und nur zwei. Eine Serifenschrift (Source Serif 4)
  für das, was man liest, weil es erzählt; eine Grotesk (Inter) für
  das, was ordnet - Rubrik, Seitenzahl, Quelle.
- Feste Größenstufen statt "so groß, wie es passt". Ein Titel ist ein
  Titel, eine Aussage eine Aussage; dazwischen springt nichts.
- Farbe als Rubrik. Das Gebiet bestimmt den Akzent: Natur salbeigrün,
  Archäologie ocker, Weltall blassblau, Forschung koralle, Kurioses
  flieder. Wer zwei Beiträge gesehen hat, erkennt das Gebiet, bevor er
  liest.
- Das Foto bleibt frei. Auf dem Titel steht die Schrift dort, wo das
  Bild ruhig ist; auf den Karten steht sie unter dem Bild, nicht darauf.
- Ruhe. Kein Strich, kein Kasten, keine Kontur - Abstand ordnet.

Alle Maße sind für 1080 Pixel Breite gedacht und skalieren mit.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

SCHRIFTORDNER = Path(__file__).resolve().parent.parent / "schriften"
SERIFE = SCHRIFTORDNER / "SourceSerif4.ttf"
GROTESK = SCHRIFTORDNER / "Inter.ttf"

GRUND = (15, 16, 18)
PAPIER = (244, 241, 234)
LEISE = (168, 165, 158)

RUBRIKFARBEN = {
    "NATUR": (140, 192, 132),
    "ARCHÄOLOGIE": (212, 165, 90),
    "WELTALL": (142, 168, 255),
    "FORSCHUNG": (232, 131, 107),
    "KURIOS": (197, 155, 224),
}
STANDARDAKZENT = (212, 165, 90)

RAND = 84


def akzent_fuer(rubrik: str) -> tuple[int, int, int]:
    return RUBRIKFARBEN.get((rubrik or "").upper(), STANDARDAKZENT)


# --- Schriften ---------------------------------------------------------------

_cache: dict[tuple, ImageFont.FreeTypeFont] = {}


def schrift(art: str, groesse: int) -> ImageFont.FreeTypeFont:
    """Eine Schrift in einer Rolle: titel, aussage, text, text_fett, klein.

    Beide Dateien sind variable Schriften. Strichstärke und optische
    Größe werden eingestellt, nicht aus verschiedenen Dateien geholt -
    so passt ein Titel in 90 Pixeln genauso zum Text in 36.
    """
    schluessel = (art, groesse)
    if schluessel in _cache:
        return _cache[schluessel]
    serife = art in ("titel", "aussage", "serife")
    datei = SERIFE if serife else GROTESK
    try:
        font = ImageFont.truetype(str(datei), groesse)
        gewicht = {
            "titel": 640, "aussage": 560, "serife": 420,
            "text": 400, "text_fett": 600, "klein": 600,
        }.get(art, 400)
        achsen = {}
        for achse in font.get_variation_axes():
            name = achse["name"]
            name = name.decode() if isinstance(name, bytes) else name
            if name.lower().startswith("weight"):
                achsen[name] = gewicht
            elif name.lower().startswith("optical"):
                lo, hi = achse["minimum"], achse["maximum"]
                achsen[name] = max(lo, min(hi, groesse * 0.75))
        font.set_variation_by_axes([achsen[k] for k in _achsreihe(font)])
    except Exception:  # noqa: BLE001 - dann die Schrift des Systems
        from .renderer import _load_font

        font = _load_font(groesse, bold=art in ("titel", "text_fett", "klein"))
    _cache[schluessel] = font
    return font


def _achsreihe(font) -> list[str]:
    reihe = []
    for achse in font.get_variation_axes():
        name = achse["name"]
        reihe.append(name.decode() if isinstance(name, bytes) else name)
    return reihe


# --- Satz --------------------------------------------------------------------


def feinsatz(text: str) -> str:
    """Deutsche Satzzeichen statt Schreibmaschine: Gedankenstrich und Anführungen.

    "Foto - ein neues" ist ein Bindestrich, wo ein Gedankenstrich hingehört;
    'Imaging' sind Hochkommas, wo ‚Imaging‘ stehen sollte. Im Magazin fällt
    beides sofort auf.
    """
    text = re.sub(r"\s-\s", " – ", text or "")
    text = re.sub(r'"([^"]+)"', r"„\1“", text)
    text = re.sub(r"(^|\s)'([^']+)'", r"\1‚\2‘", text)
    return text.strip()


def _kern(wort: str) -> str:
    return wort.strip(".,;:!?\"'„“–-()").casefold()


def umbrechen(zeichnung, text: str, font, breite: int) -> list[str]:
    zeilen, jetzt = [], ""
    for wort in text.split():
        probe = f"{jetzt} {wort}".strip()
        if zeichnung.textlength(probe, font=font) <= breite or not jetzt:
            jetzt = probe
        else:
            zeilen.append(jetzt)
            jetzt = wort
    if jetzt:
        zeilen.append(jetzt)
    return zeilen


def passend(zeichnung, text: str, art: str, breite: int, *, gross: int, klein: int,
            hoechstens: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Die größte Stufe, bei der der Text in höchstens so viele Zeilen passt."""
    for groesse in range(gross, klein - 1, -4):
        font = schrift(art, groesse)
        zeilen = umbrechen(zeichnung, text, font, breite)
        if len(zeilen) <= hoechstens and all(
            zeichnung.textlength(z, font=font) <= breite for z in zeilen
        ):
            return font, zeilen
    font = schrift(art, klein)
    return font, umbrechen(zeichnung, text, font, breite)


def setze(zeichnung, xy, zeilen, font, farbe, *, akzent=None, kerne=frozenset(),
          zeilenabstand: float = 1.12) -> int:
    """Setzt Zeilen Wort für Wort; Akzentwörter in der Akzentfarbe. Gibt das untere y zurück."""
    x0, y = xy
    hoehe = int(font.size * zeilenabstand)
    leer = zeichnung.textlength(" ", font=font)
    for zeile in zeilen:
        x = x0
        for wort in zeile.split():
            farbe_wort = akzent if akzent and _kern(wort) in kerne else farbe
            zeichnung.text((x, y), wort, font=font, fill=farbe_wort)
            x += zeichnung.textlength(wort, font=font) + leer
        y += hoehe
    return y


def gesperrt(zeichnung, xy, text: str, font, farbe, abstand: float = 0.14) -> int:
    """Versalien mit Luft dazwischen - für Rubrik und kleine Marken."""
    x, y = xy
    luft = font.size * abstand
    for zeichen in text:
        zeichnung.text((x, y), zeichen, font=font, fill=farbe)
        x += zeichnung.textlength(zeichen, font=font) + luft
    return int(x)


def akzentkerne(akzentwort: str, text: str) -> frozenset[str]:
    vorhanden = {_kern(w) for w in text.split()}
    gewuenscht = {_kern(w) for w in (akzentwort or "").split()}
    treffer = {k for k in gewuenscht if k and k in vorhanden}
    if treffer:
        return frozenset(treffer)
    return frozenset(_kern(w) for w in text.split() if any(z.isdigit() for z in w))


# --- Bild --------------------------------------------------------------------


def auf_format(bild: Image.Image, groesse: tuple[int, int], *, oben_anteil: float = 0.4):
    from .overlay import _auf_format

    if oben_anteil == 0.4:
        return _auf_format(bild, groesse)
    ziel_b, ziel_h = groesse
    faktor = max(ziel_b / bild.width, ziel_h / bild.height)
    neu = bild.resize((round(bild.width * faktor), round(bild.height * faktor)), Image.LANCZOS)
    links = (neu.width - ziel_b) // 2
    oben = max(0, int((neu.height - ziel_h) * oben_anteil))
    return neu.crop((links, oben, links + ziel_b, oben + ziel_h))


def unruhe(bild: Image.Image, kasten: tuple[int, int, int, int]) -> float:
    """Wie viel in einem Ausschnitt los ist - Kanten je Bildpunkt.

    Dort, wo wenig los ist, kann Schrift stehen, ohne etwas zu verdecken.
    """
    ausschnitt = bild.crop(kasten).convert("L").resize((120, 60))
    kanten = ausschnitt.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(kanten).mean[0])


def verlauf(bild: Image.Image, *, von_unten: bool, anteil: float, staerke: int = 235) -> None:
    breite, hoehe = bild.size
    h = int(hoehe * anteil)
    maske = Image.new("L", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        t = t if von_unten else 1 - t
        # Langsam beginnen, unten satt werden - wie ein Bild, das im
        # Dunkel ausläuft, nicht wie ein Balken.
        maske.putpixel((0, y), int(staerke * (t ** 1.7)))
    maske = maske.resize((breite, h))
    schwarz = Image.new("RGB", (breite, h), GRUND)
    bild.paste(schwarz, (0, hoehe - h if von_unten else 0), maske)


# --- Rahmen ------------------------------------------------------------------


def kopfzeile(zeichnung, breite: int, *, rubrik: str, seite: str, akzent, auf_foto: bool):
    """Oben: Rubrik links, Seitenzahl rechts. Klein, ruhig, immer gleich."""
    klein = schrift("klein", 24)
    y = 58
    if rubrik:
        zeichnung.ellipse([(RAND, y + 8), (RAND + 11, y + 19)], fill=akzent)
        gesperrt(zeichnung, (RAND + 22, y), rubrik, klein, akzent)
    if seite:
        font = schrift("text", 24)
        laenge = zeichnung.textlength(seite, font=font)
        zeichnung.text((breite - RAND - laenge, y), seite, font=font,
                       fill=PAPIER if auf_foto else LEISE)


def fusszeile(zeichnung, breite: int, hoehe: int, *, links: str = "", rechts: str = "",
              farbe=LEISE):
    font = schrift("text_fett", 24)
    if links:
        zeichnung.text((RAND, hoehe - 62), links, font=font, fill=farbe, anchor="ls")
    if rechts:
        laenge = zeichnung.textlength(rechts, font=font)
        zeichnung.text((breite - RAND - laenge, hoehe - 62), rechts, font=font, fill=farbe,
                       anchor="ls")


# --- Die Layouts ---------------------------------------------------------------


def titel(foto: Path | None, ziel: Path, *, ueberschrift: str, unterzeile: str = "",
          akzentwort: str = "", rubrik: str = "", handle: str = "", wischen: bool = False,
          groesse=(1080, 1350)) -> Path:
    """Das erste Bild: das Foto randlos, die Überschrift dort, wo es ruhig ist."""
    breite, hoehe = groesse
    akzent = akzent_fuer(rubrik)
    ueberschrift, unterzeile = feinsatz(ueberschrift), feinsatz(unterzeile)
    if foto is not None:
        bild = auf_format(Image.open(foto).convert("RGB"), groesse)
        oben_ruhiger = unruhe(bild, (0, 0, breite, hoehe // 3)) + 6 < unruhe(
            bild, (0, hoehe * 2 // 3, breite, hoehe)
        )
    else:
        bild = Image.new("RGB", groesse, GRUND)
        oben_ruhiger = False
    von_unten = not oben_ruhiger
    if foto is not None:
        verlauf(bild, von_unten=von_unten, anteil=0.62)
        verlauf(bild, von_unten=not von_unten, anteil=0.18, staerke=150)
    zeichnung = ImageDraw.Draw(bild)
    innen = breite - 2 * RAND

    font, zeilen = passend(zeichnung, ueberschrift, "titel", innen, gross=96, klein=60,
                           hoechstens=4)
    zeilenhoehe = int(font.size * 1.08)
    sub = schrift("text", 32)
    subzeilen = umbrechen(zeichnung, unterzeile, sub, innen)[:2] if unterzeile else []
    block = len(zeilen) * zeilenhoehe + (len(subzeilen) * 44 + 22 if subzeilen else 0)

    if von_unten:
        y = hoehe - 130 - block
    else:
        y = 150
    if foto is None:
        y = (hoehe - block) // 2
    kerne = akzentkerne(akzentwort, ueberschrift)
    y = setze(zeichnung, (RAND, y), zeilen, font, PAPIER, akzent=akzent, kerne=kerne,
              zeilenabstand=1.08)
    if subzeilen:
        y += 22
        setze(zeichnung, (RAND, y), subzeilen, sub, (222, 219, 212), zeilenabstand=1.38)

    kopfzeile(zeichnung, breite, rubrik=rubrik, seite="", akzent=akzent, auf_foto=foto is not None)
    fusszeile(zeichnung, breite, hoehe, links=handle, rechts="Wischen →" if wischen else "",
              farbe=PAPIER if foto is not None else LEISE)
    return _speichern(bild, ziel)


def karte_mit_foto(foto: Path, ziel: Path, *, text: str, akzentwort: str = "",
                   rubrik: str = "", seite: str = "", groesse=(1080, 1350)) -> Path:
    """Das Foto oben, frei; darunter der Satz, ruhig gesetzt.

    Die Schrift liegt nicht auf dem Bild. Was man sehen will, bleibt
    sichtbar - und der Satz liest sich wie eine Bildunterschrift im
    Magazin, nicht wie ein Aufkleber.
    """
    breite, hoehe = groesse
    akzent = akzent_fuer(rubrik)
    bild = Image.new("RGB", groesse, GRUND)
    zeichnung = ImageDraw.Draw(bild)
    innen = breite - 2 * RAND

    text = feinsatz(text)
    font, zeilen = passend(zeichnung, text, "aussage", innen, gross=60, klein=42, hoechstens=4)
    textblock = len(zeilen) * int(font.size * 1.18)
    # Das Foto bekommt so viel Fläche, wie der Satz übrig lässt - mindestens
    # gut die Hälfte, höchstens zwei Drittel.
    fotohoehe = min(int(hoehe * 0.66), max(int(hoehe * 0.55), hoehe - textblock - 240))
    foto_bild = auf_format(Image.open(foto).convert("RGB"), (breite, fotohoehe), oben_anteil=0.45)
    bild.paste(foto_bild, (0, 0))
    # Oben ein Hauch Dunkel, damit Rubrik und Seitenzahl tragen; unten
    # läuft das Foto in den Grund aus statt an einer Kante zu enden.
    verlauf(bild, von_unten=False, anteil=0.14, staerke=150)
    streifen = bild.crop((0, 0, breite, fotohoehe))
    verlauf(streifen, von_unten=True, anteil=0.22, staerke=255)
    bild.paste(streifen, (0, 0))
    zeichnung = ImageDraw.Draw(bild)

    # Mittig in der Fläche unter dem Foto, etwas nach oben gerückt -
    # optisch mittig ist nicht rechnerisch mittig.
    frei = hoehe - fotohoehe
    y = fotohoehe + max(30, int((frei - textblock) * 0.42))
    setze(zeichnung, (RAND, y), zeilen, font, PAPIER, akzent=akzent,
          kerne=akzentkerne(akzentwort, text), zeilenabstand=1.18)
    kopfzeile(zeichnung, breite, rubrik=rubrik, seite=seite, akzent=akzent, auf_foto=True)
    return _speichern(bild, ziel)


_ZAHL = re.compile(r"\d[\d.,]*(?:\s?(?:-?[Ff]ache|%|Prozent|Meter|Jahre|km|Millionen|Milliarden))?")


def karte_ohne_foto(ziel: Path, *, text: str, akzentwort: str = "", rubrik: str = "",
                    seite: str = "", groesse=(1080, 1350)) -> Path:
    """Ohne Foto: eine große Zahl, wenn eine da ist - sonst eine große Aussage."""
    breite, hoehe = groesse
    akzent = akzent_fuer(rubrik)
    bild = Image.new("RGB", groesse, GRUND)
    zeichnung = ImageDraw.Draw(bild)
    innen = breite - 2 * RAND
    text = feinsatz(text)

    zahl = _ZAHL.search(text)
    if zahl and len(zahl.group(0)) <= 14:
        gross, _ = passend(zeichnung, zahl.group(0), "titel", innen, gross=230, klein=120,
                           hoechstens=1)
        font, zeilen = passend(zeichnung, text, "aussage", innen, gross=52, klein=40,
                               hoechstens=5)
        block = int(gross.size * 1.05) + 40 + len(zeilen) * int(font.size * 1.2)
        y = (hoehe - block) // 2
        zeichnung.text((RAND - 6, y), zahl.group(0), font=gross, fill=akzent)
        y += int(gross.size * 1.05) + 40
        setze(zeichnung, (RAND, y), zeilen, font, PAPIER, zeilenabstand=1.2)
    else:
        font, zeilen = passend(zeichnung, text, "aussage", innen, gross=84, klein=52,
                               hoechstens=6)
        block = len(zeilen) * int(font.size * 1.14)
        y = (hoehe - block) // 2
        setze(zeichnung, (RAND, y), zeilen, font, PAPIER, akzent=akzent,
              kerne=akzentkerne(akzentwort, text), zeilenabstand=1.14)

    kopfzeile(zeichnung, breite, rubrik=rubrik, seite=seite, akzent=akzent, auf_foto=False)
    return _speichern(bild, ziel)


def abschluss(ziel: Path, *, frage: str, quelle: str, handle: str, rubrik: str = "",
              seite: str = "", groesse=(1080, 1350)) -> Path:
    """Die letzte Karte: die Quelle immer, die Frage nur, wenn es eine gibt."""
    breite, hoehe = groesse
    akzent = akzent_fuer(rubrik)
    bild = Image.new("RGB", groesse, GRUND)
    zeichnung = ImageDraw.Draw(bild)
    innen = breite - 2 * RAND
    klein = schrift("klein", 24)

    frage, quelle = feinsatz(frage), feinsatz(quelle)
    y = 250
    if frage:
        font, zeilen = passend(zeichnung, frage, "aussage", innen, gross=64, klein=44,
                               hoechstens=6)
        y = setze(zeichnung, (RAND, y), zeilen, font, PAPIER, zeilenabstand=1.18)
        y += 70
    if quelle:
        gesperrt(zeichnung, (RAND, y), "QUELLE", klein, akzent)
        y += 44
        text = schrift("text", 30)
        setze(zeichnung, (RAND, y), umbrechen(zeichnung, quelle, text, innen)[:4], text,
              (214, 211, 204), zeilenabstand=1.42)

    marke = schrift("titel", 44)
    zeichnung.text((RAND, hoehe - 150), handle, font=marke, fill=PAPIER, anchor="ls")
    zeichnung.text((RAND, hoehe - 100), "Jeden Tag ein Fund, den du sonst verpasst hättest.",
                   font=schrift("text", 26), fill=LEISE, anchor="ls")
    kopfzeile(zeichnung, breite, rubrik=rubrik, seite=seite, akzent=akzent, auf_foto=False)
    return _speichern(bild, ziel)


def _speichern(bild: Image.Image, ziel: Path) -> Path:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ziel, "PNG", optimize=True)
    return ziel


__all__ = [
    "RUBRIKFARBEN",
    "abschluss",
    "akzent_fuer",
    "karte_mit_foto",
    "karte_ohne_foto",
    "schrift",
    "titel",
]
