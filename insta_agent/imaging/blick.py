"""Ein Bild ansehen lassen, bevor es in den Beitrag kommt.

Alles, was die Bildsuche bisher weiss, steht neben dem Bild und nicht
darin: der Dateiname, die Lizenz, die Pixelmasse, der Platz in der
Trefferliste. Daran laesst sich messen, ob ein Bild gross genug, scharf
genug und gut geschnitten ist. Ob es die Sache zeigt, um die es geht,
laesst sich daran nicht messen.

Zweimal hintereinander hat genau das den Beitrag ruiniert. Bei "deep sea
creature" gewann erst "Humpback anglerfish.png" - eine wissenschaftliche
Zeichnung auf Weiss - und danach "2018 NYEC in Dalian (Self-participation;
Deep Sea Legend following Fireworks)", ein Feuerwerk, das die gesuchten
Worte im Dateinamen hat. Beide Male war das Bild nach allen messbaren
Merkmalen tadellos.

Die Zeichnung faengt inzwischen die Fotopruefung ab. Das Feuerwerk faengt
nichts ab, denn es ist eine hervorragende Fotografie - nur eben von
etwas anderem. Dagegen hilft nur hinsehen.

Ein kleines Modell reicht dafuer vollkommen. Die Frage ist nicht, was auf
dem Bild alles zu sehen ist, sondern ob es zum Thema gehoert - und dafuer
genuegen ein paar hundert Bildpunkte. Deshalb wird das Bild vor der Frage
auf 512 Pixel heruntergerechnet: Das kostet rund ein Zwanzigstel Cent
statt eines halben, und die Antwort wird davon nicht schlechter.

Das Ergebnis ist eine Zahl von 0 bis 10 und kein Ja oder Nein. Ein
Ausschluss waere wieder derselbe Fehler wie bei der Schaerfe: Ein
einzelnes Merkmal entscheidet allein, und irgendwann entscheidet es
falsch. Die Zahl geht als Faktor in die Punktzahl ein, neben Rang,
Eignung und Schaerfe.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# So gross geht das Bild zur Frage. Mehr Bildpunkte kosten mehr und
# beantworten dieselbe Frage nicht besser: "Ist das ein Tiefseewesen
# oder ein Feuerwerk" entscheidet sich nicht an den Einzelheiten.
FRAGEBREITE = 512

# Wie die Antwort aussehen soll. Eine Zahl, ein Strich, ein Satz.
ANTWORTFORM = "ZAHL|kurze Beschreibung"

FRAGE = """Du pruefst Bilder fuer einen Instagram-Beitrag.

Das Thema ist: {thema}

Sieh dir das Bild an und sage, wie gut es zu diesem Thema passt:

10 = zeigt genau die Sache, um die es geht
7  = zeigt etwas, das eng dazugehoert
4  = passt nur entfernt, aber nicht falsch
1  = zeigt etwas anderes
0  = hat mit dem Thema nichts zu tun

Wichtig: Ein Bild, das die gesuchten Worte nur im Namen traegt, aber
etwas anderes zeigt, bekommt 0 oder 1. Ein Feuerwerk ist kein Tiefseetier,
auch wenn es "Deep Sea Legend" heisst.

Antworte in genau einer Zeile, in dieser Form:
{form}

Die Beschreibung auf Deutsch, hoechstens acht Woerter, und sie sagt, was
wirklich zu sehen ist - nicht, was zu sehen sein sollte."""

# Was zurueckkommt, wenn nicht gefragt werden konnte. Nicht null:
# Eine Pruefung, die nicht stattgefunden hat, darf kein Bild abwerten.
UNGEPRUEFT = -1


def verkleinere_zur_frage(pfad: Path, *, breite: int = FRAGEBREITE) -> tuple[str, str]:
    """Das Bild klein und als Text, so wie die Schnittstelle es will.

    Gibt die Daten und den Medientyp zurueck. JPEG, weil das bei
    Fotografien deutlich weniger Zeichen ergibt als PNG - und uebertragen
    wird jedes Zeichen.
    """
    with Image.open(pfad) as offen:
        bild = offen.convert("RGB")
        if bild.width > breite:
            hoehe = max(1, round(bild.height * breite / bild.width))
            bild = bild.resize((breite, hoehe), Image.LANCZOS)
        puffer = io.BytesIO()
        bild.save(puffer, format="JPEG", quality=80)
    return base64.standard_b64encode(puffer.getvalue()).decode("ascii"), "image/jpeg"


def lies_antwort(text: str) -> tuple[int, str]:
    """Macht aus der Zeile des Modells eine Zahl und einen Satz.

    Nachsichtig, und das mit Absicht: Ob die Antwort "7|Ein Tiefseefisch"
    heisst, "7 - Ein Tiefseefisch" oder nur "7", aendert nichts an dem,
    was sie bedeutet. An der Form einer Antwort zu scheitern, die
    inhaltlich stimmt, waere die teuerste Art von Fehler - die Frage ist
    dann bezahlt und das Ergebnis weg.
    """
    sauber = (text or "").strip()
    if not sauber:
        return UNGEPRUEFT, ""
    treffer = re.match(r"\s*(\d{1,2})\s*[|:\-–]?\s*(.*)", sauber)
    if not treffer:
        return UNGEPRUEFT, sauber[:60]
    punkte = min(10, int(treffer.group(1)))
    return punkte, treffer.group(2).strip()[:60]


def blickfaktor(punkte: int) -> float:
    """Was die Antwort fuer die Auswahl bedeutet.

    Ungeprueft heisst 1,0 - kein Abzug fuer etwas, das nicht stattgefunden
    hat. Sonst laeuft es von 0,25 bei null Punkten bis 1,0 bei zehn.

    Unten wird nicht auf null gegangen, und das ist kein Zoegern: Wenn
    jedes Bild durchfaellt, ist ein schlecht passendes echtes Foto immer
    noch besser als gar keins. Der Abstand reicht trotzdem - ein
    Feuerwerk mit einem Punkt kommt auf 0,33 und hat gegen ein
    Tiefseefoto mit neun (0,93) keine Aussicht mehr.
    """
    if punkte < 0:
        return 1.0
    return 0.25 + 0.075 * max(0, min(10, punkte))


__all__ = [
    "FRAGE",
    "FRAGEBREITE",
    "UNGEPRUEFT",
    "blickfaktor",
    "lies_antwort",
    "verkleinere_zur_frage",
]
