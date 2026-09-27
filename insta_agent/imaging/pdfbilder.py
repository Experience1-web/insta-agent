"""Die Abbildungen einer Studie in voller Groesse - aus ihrem PDF.

Ueber das oeffentliche Archiv kommen zu jeder offenen Studie die
Abbildungen als Bilddateien. Nur sind das Vorschaufassungen: Bei der
Studie zur leuchtenden Koralle 749 x 570 Pixel, dazu als Tafel aus vier
Einzelbildern mit Buchstaben und Massstabsbalken. Auf Instagram hiesse
das: ein Viertel davon, dreifach hochgerechnet.

Im PDF derselben Studie liegen dieselben Aufnahmen einzeln und in der
Groesse, in der sie gedruckt werden - 2000 x 1500, 2272 x 1511. Die
Buchstaben und Balken sind dort Text und Linien, keine Bildpunkte; die
Aufnahme selbst ist sauber.

Ausgelesen wird ohne eine weitere Bibliothek. Ein PDF ist eine Folge
nummerierter Objekte; Bilder darunter tragen "/Subtype /Image" und ihre
Masse im Kopf. Gespeichert sind sie auf zwei Arten:

- als JPEG ("DCTDecode") - dann sind die Daten schon eine Bilddatei,
- komprimiert wie ein PNG ("FlateDecode" mit Predictor) - dann sind es
  genau die Daten, die in einer PNG-Datei stehen, und Pillow liest sie,
  sobald man den PNG-Rahmen darum legt.

Druckdateien speichern Farbe oft als CMYK. Das eingebettete Farbprofil
wird dann benutzt, um sauber nach RGB umzurechnen; fehlt es, wird
einfach umgerechnet.

Was hier nicht gelesen wird, faellt still heraus: andere Kompressionen,
Bilder in komprimierten Objektsammlungen, verschluesselte PDFs. Dann
bleibt es bei den Vorschaufassungen aus dem Archiv.
"""

from __future__ import annotations

import io
import logging
import re
import struct
import zlib
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# Kleiner lohnt es sich nicht: Das sind Symbole, Logos, Vorschaubildchen.
MINDESTKANTE = 900

# Mehr Bilder aus einem PDF braucht kein Beitrag.
HOECHSTENS = 12

_OBJEKT = re.compile(rb"(?<![0-9])(\d+)\s+0\s+obj\b")


def _objekte(pdf: bytes) -> dict[int, int]:
    """Wo jedes Objekt beginnt: Nummer -> Stelle im PDF (die letzte zaehlt)."""
    return {int(m.group(1)): m.end() for m in _OBJEKT.finditer(pdf)}


def _kopf_und_strom(pdf: bytes, beginn: int, stellen: dict[int, int]) -> tuple[bytes, bytes | None]:
    """Der Kopf eines Objekts und - falls es einen hat - sein Datenstrom."""
    ende_obj = pdf.find(b"endobj", beginn)
    marke = pdf.find(b"stream", beginn)
    if marke < 0 or (0 <= ende_obj < marke):
        return pdf[beginn : ende_obj if ende_obj >= 0 else beginn + 2000], None

    kopf = pdf[beginn:marke]
    start = marke + len(b"stream")
    if pdf[start : start + 2] == b"\r\n":
        start += 2
    elif pdf[start : start + 1] in (b"\n", b"\r"):
        start += 1

    laenge = None
    if treffer := re.search(rb"/Length\s+(\d+)\s+0\s+R", kopf):
        ziel = stellen.get(int(treffer.group(1)))
        if ziel is not None and (zahl := re.match(rb"\s*(\d+)", pdf[ziel : ziel + 40])):
            laenge = int(zahl.group(1))
    elif treffer := re.search(rb"/Length\s+(\d+)", kopf):
        laenge = int(treffer.group(1))

    if laenge is None or start + laenge > len(pdf):
        laenge = max(0, pdf.find(b"endstream", start) - start)
    return kopf, pdf[start : start + laenge]


def _zahl(kopf: bytes, name: bytes) -> int | None:
    treffer = re.search(rb"/" + name + rb"\s*(\d+)", kopf)
    return int(treffer.group(1)) if treffer else None


def _png(breite: int, hoehe: int, kanaele: int, daten: bytes) -> bytes:
    """Legt einen PNG-Rahmen um Daten, die schon PNG-komprimiert sind."""
    farbtyp = {1: 0, 3: 2, 4: 6}[kanaele]

    def block(art: bytes, inhalt: bytes) -> bytes:
        pruef = zlib.crc32(art + inhalt) & 0xFFFFFFFF
        return struct.pack(">I", len(inhalt)) + art + inhalt + struct.pack(">I", pruef)

    kopf = struct.pack(">IIBBBBB", breite, hoehe, 8, farbtyp, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + block(b"IHDR", kopf)
        + block(b"IDAT", daten)
        + block(b"IEND", b"")
    )


def _farbprofil(pdf: bytes, kopf: bytes, stellen: dict[int, int]) -> bytes | None:
    """Das eingebettete ICC-Profil eines Bildes, entpackt - oder None."""
    verweis = re.search(rb"/ColorSpace\s*(\d+)\s+0\s+R", kopf)
    raum = kopf
    if verweis and (stelle := stellen.get(int(verweis.group(1)))) is not None:
        raum, _ = _kopf_und_strom(pdf, stelle, stellen)
    icc = re.search(rb"/ICCBased\s*(\d+)\s+0\s+R", raum)
    if not icc or (stelle := stellen.get(int(icc.group(1)))) is None:
        return None
    profilkopf, strom = _kopf_und_strom(pdf, stelle, stellen)
    if strom is None:
        return None
    try:
        return zlib.decompress(strom) if b"FlateDecode" in profilkopf else strom
    except zlib.error:
        return None


def _nach_rgb(bild: Image.Image, profil: bytes | None) -> Image.Image:
    if bild.mode == "RGB":
        return bild
    if bild.mode == "CMYK" and profil:
        try:
            from PIL import ImageCms

            return ImageCms.profileToProfile(
                bild,
                ImageCms.ImageCmsProfile(io.BytesIO(profil)),
                ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )
        except Exception as exc:  # noqa: BLE001 - dann eben einfach
            log.debug("Farbprofil nicht verwendbar: %s", exc)
    return bild.convert("RGB")


def bilder_aus_pdf(pdf: bytes, ziel_ordner: Path, stamm: str) -> list[Path]:
    """Schreibt die grossen Bilder eines PDF als JPEG-Dateien. Groesste zuerst.

    Leer heisst: keine lesbaren Bilder in brauchbarer Groesse.
    """
    if not pdf.startswith(b"%PDF") or b"/Encrypt" in pdf[-4096:]:
        return []

    stellen = _objekte(pdf)
    gefunden: list[tuple[int, Image.Image]] = []
    for nummer, beginn in stellen.items():
        kopf, strom = _kopf_und_strom(pdf, beginn, stellen)
        if strom is None or not re.search(rb"/Subtype\s*/Image", kopf):
            continue
        breite, hoehe = _zahl(kopf, b"Width"), _zahl(kopf, b"Height")
        if not breite or not hoehe or max(breite, hoehe) < MINDESTKANTE:
            continue
        if _zahl(kopf, b"BitsPerComponent") not in (None, 8):
            continue

        try:
            if b"DCTDecode" in kopf:
                bild = Image.open(io.BytesIO(strom))
                bild.load()
            elif b"FlateDecode" in kopf and _zahl(kopf, b"Predictor") and (_zahl(kopf, b"Predictor") or 0) >= 10:
                kanaele = _zahl(kopf, b"Colors") or 1
                if kanaele not in (1, 3, 4):
                    continue
                bild = Image.open(io.BytesIO(_png(breite, hoehe, kanaele, strom)))
                bild.load()
                if kanaele == 4:
                    bild = Image.frombytes("CMYK", bild.size, bild.tobytes())
            elif b"FlateDecode" in kopf:
                roh = zlib.decompress(strom)
                kanaele = len(roh) // (breite * hoehe) if breite * hoehe else 0
                modus = {1: "L", 3: "RGB", 4: "CMYK"}.get(kanaele)
                if not modus:
                    continue
                bild = Image.frombytes(modus, (breite, hoehe), roh[: breite * hoehe * kanaele])
            else:
                continue
        except Exception as exc:  # noqa: BLE001 - ein Bild weniger
            log.debug("PDF-Objekt %s nicht lesbar: %s", nummer, exc)
            continue

        if bild.mode == "CMYK" and b"DCTDecode" in kopf and b"/Decode" in kopf:
            # Adobe-JPEGs speichern CMYK umgekehrt; der Kopf sagt es mit /Decode.
            from PIL import ImageChops

            bild = ImageChops.invert(bild)
        gefunden.append((breite * hoehe, _nach_rgb(bild, _farbprofil(pdf, kopf, stellen))))

    gefunden.sort(key=lambda paar: paar[0], reverse=True)
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    pfade: list[Path] = []
    for nummer, (_, bild) in enumerate(gefunden[:HOECHSTENS], start=1):
        pfad = ziel_ordner / f"{stamm}-pdf{nummer}.jpg"
        bild.convert("RGB").save(pfad, "JPEG", quality=92)
        pfade.append(pfad)
    return pfade


__all__ = ["bilder_aus_pdf"]
