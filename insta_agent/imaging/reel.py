"""Aus einem Karussell ein Reel - dieselben Bilder, als kurzes Video.

Instagram zeigt Reels deutlich mehr Leuten, die dem Account noch nicht
folgen, als Bildbeiträgen. Der Inhalt ist schon da: Titelbild und Karten
erzählen die Geschichte in der richtigen Reihenfolge. Daraus wird hier
ein Video, ohne weitere KI und ohne Kosten.

Aufbau je Bild: Das Bild steht vollständig in der Mitte, samt Schrift -
im 4:5-Format, wie im Feed. Dahinter füllt dasselbe Bild, groß gezogen,
weichgezeichnet und abgedunkelt, das Hochformat aus. Das Bild selbst
zoomt langsam heran (so bleibt das Auge dran), und das nächste Bild
schiebt sich von rechts herein - wie beim Wischen durchs Karussell.
Überblenden wirkte unruhig: Zwei Schriften liefen ineinander.

Das Video bekommt eine stille Tonspur. Musik lässt sich über die
Schnittstelle nicht anhängen; wer das Reel von Hand hochlädt, kann in
der Instagram-App einen Ton darunterlegen - das hilft der Reichweite.

Kodiert wird mit ffmpeg aus dem Paket `imageio-ffmpeg`. Das bringt das
Programm für Windows, Mac und Linux selbst mit; fehlt es, gibt es eben
kein Reel, und der Beitrag geht als Karussell hinaus wie bisher.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

log = logging.getLogger(__name__)

REEL = (1080, 1920)
BILDER_JE_SEKUNDE = 30
SEKUNDEN_JE_BILD = 3.2
UEBERBLENDUNG = 0.45  # Sekunden, die das Hereinschieben dauert
ZOOM = 0.07  # so viel waechst ein Bild waehrend seiner Zeit


class ReelFehler(RuntimeError):
    """Das Video liess sich nicht bauen."""


def ffmpeg_pfad() -> str | None:
    """Das mitgelieferte ffmpeg - oder None, wenn das Paket fehlt."""
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001 - dann eben kein Reel
        log.info("ffmpeg nicht verfuegbar: %s", exc)
        return None


def kann_reels() -> bool:
    return ffmpeg_pfad() is not None


def _hintergrund(bild: Image.Image, groesse: tuple[int, int]) -> Image.Image:
    """Das Bild, auf das Hochformat gezogen, weich und dunkel - der Rahmen."""
    breite, hoehe = groesse
    faktor = max(breite / bild.width, hoehe / bild.height)
    gross = bild.resize(
        (max(1, round(bild.width * faktor)), max(1, round(bild.height * faktor))),
        Image.BILINEAR,
    )
    links = (gross.width - breite) // 2
    oben = (gross.height - hoehe) // 2
    gross = gross.crop((links, oben, links + breite, oben + hoehe))
    # Klein weichzeichnen und wieder gross ziehen: gleicher Effekt, ein
    # Bruchteil der Rechenzeit.
    klein = gross.resize((breite // 8, hoehe // 8), Image.BILINEAR)
    klein = klein.filter(ImageFilter.GaussianBlur(6))
    weich = klein.resize(groesse, Image.BILINEAR)
    return ImageEnhance.Brightness(weich).enhance(0.45)


def _vordergrund_mass(bild: Image.Image, groesse: tuple[int, int]) -> tuple[int, int]:
    """Das Bild vollständig sichtbar, so breit wie das Video."""
    breite, hoehe = groesse
    faktor = min(breite / bild.width, hoehe * 0.86 / bild.height)
    return max(1, round(bild.width * faktor)), max(1, round(bild.height * faktor))


def _bild_zum_zeitpunkt(
    bild: Image.Image,
    hintergrund: Image.Image,
    mass: tuple[int, int],
    anteil: float,
    groesse: tuple[int, int],
) -> Image.Image:
    """Ein Standbild: Hintergrund, darauf das Bild, um `anteil` herangezoomt."""
    zoom = 1.0 + ZOOM * anteil
    w, h = round(mass[0] * zoom), round(mass[1] * zoom)
    vorn = bild.resize((w, h), Image.BILINEAR)
    # Beim Heranzoomen wird der Rand beschnitten, damit das Bild nicht
    # ueber die Videobreite hinauswaechst.
    if w > groesse[0]:
        rand = (w - groesse[0]) // 2
        vorn = vorn.crop((rand, 0, rand + groesse[0], h))
        w = groesse[0]
    stand = hintergrund.copy()
    stand.paste(vorn, ((groesse[0] - w) // 2, (groesse[1] - h) // 2))
    return stand


def baue_reel(
    bilder: list[Path],
    ziel: Path,
    *,
    sekunden_je_bild: float = SEKUNDEN_JE_BILD,
    ueberblendung: float = UEBERBLENDUNG,
    fps: int = BILDER_JE_SEKUNDE,
    groesse: tuple[int, int] = REEL,
) -> Path:
    """Schreibt das Reel als MP4 (H.264, stille Tonspur) und gibt den Pfad zurück."""
    ffmpeg = ffmpeg_pfad()
    if ffmpeg is None:
        raise ReelFehler(
            "Für Reels fehlt ffmpeg. Einmal „6 - Neue Version holen“ ausführen - "
            "das installiert es mit."
        )
    vorhanden = [Path(b) for b in bilder if b and Path(b).is_file()]
    if not vorhanden:
        raise ReelFehler("Es gibt keine Bilder, aus denen ein Reel werden könnte.")

    geladen = [Image.open(b).convert("RGB") for b in vorhanden]
    gruende = [_hintergrund(b, groesse) for b in geladen]
    masse = [_vordergrund_mass(b, groesse) for b in geladen]
    je_bild = max(1, round(sekunden_je_bild * fps))
    blende = min(max(0, round(ueberblendung * fps)), je_bild // 2)

    ziel.parent.mkdir(parents=True, exist_ok=True)
    befehl = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{groesse[0]}x{groesse[1]}", "-r", str(fps), "-i", "-",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        str(ziel),
    ]
    prozess = subprocess.Popen(
        befehl, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        for nummer, (bild, grund, mass) in enumerate(zip(geladen, gruende, masse)):
            naechstes = nummer + 1 < len(geladen)
            for schritt in range(je_bild):
                anteil = schritt / max(1, je_bild - 1)
                stand = _bild_zum_zeitpunkt(bild, grund, mass, anteil, groesse)
                # Zum Ende schiebt sich das naechste Bild herein.
                if naechstes and schritt >= je_bild - blende:
                    t = (schritt - (je_bild - blende) + 1) / (blende + 1)
                    t = t * t * (3 - 2 * t)  # sanft an, sanft aus
                    danach = _bild_zum_zeitpunkt(
                        geladen[nummer + 1], gruende[nummer + 1], masse[nummer + 1], 0.0, groesse
                    )
                    versatz = round(groesse[0] * t)
                    wisch = Image.new("RGB", groesse)
                    wisch.paste(stand, (-versatz, 0))
                    wisch.paste(danach, (groesse[0] - versatz, 0))
                    stand = wisch
                prozess.stdin.write(stand.tobytes())
        prozess.stdin.close()
        fehler = prozess.stderr.read().decode("utf-8", "replace")
        if prozess.wait(timeout=300) != 0:
            raise ReelFehler(f"ffmpeg brach ab: {fehler.strip()[:300]}")
    except BrokenPipeError as exc:
        fehler = prozess.stderr.read().decode("utf-8", "replace") if prozess.stderr else ""
        prozess.kill()
        raise ReelFehler(f"ffmpeg brach ab: {fehler.strip()[:300]}") from exc
    finally:
        for b in geladen:
            b.close()

    log.info("Reel gebaut: %s (%s Bilder)", ziel.name, len(geladen))
    return ziel


def ist_aktuell(reel: Path | None, bilder: list[Path]) -> bool:
    """Ist das Reel jünger als jedes seiner Bilder? Sonst zeigt es Altes."""
    if reel is None or not Path(reel).is_file():
        return False
    stand = Path(reel).stat().st_mtime
    return all(
        Path(b).stat().st_mtime <= stand for b in bilder if b and Path(b).is_file()
    )


__all__ = ["REEL", "ReelFehler", "baue_reel", "ffmpeg_pfad", "ist_aktuell", "kann_reels"]
