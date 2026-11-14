"""Die Schlussredaktion: jemand, der den fertigen Beitrag ansieht, bevor er rausgeht.

Bisher prüfte nur die Endprüfung, und die fragt eine einzige Sache: ob
stimmt, was dasteht. Ob es sich gut liest, ob die Geschichte einen
roten Faden hat, ob das Bild zum Satz passt, ob die Schrift etwas
verdeckt - das hat niemand angesehen. Vor allem hat niemand die fertigen
Bilder gesehen. Man sieht einem Beitrag vieles erst an, wenn er gesetzt
ist: fünfmal dasselbe Foto, ein Satz, der unter dem Bild nichts
bedeutet, eine Zahl, die schon auf der vorigen Karte stand.

Die Schlussredaktion bekommt deshalb alle Bilder auf einem Blatt, dazu
die Texte, und darf eines: umformulieren und kürzen. Keine neue
Tatsache, keine neue Zahl - die Fakten hat die Endprüfung abgenommen,
und jede Änderung geht danach noch einmal durch die Nachprüfung.

Kosten: ein Bild und etwas Text an das Recherchemodell, rund zwei Cent.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field

from ..llm import Brain
from ..models import PostDraft
from .prompts import with_context

log = logging.getLogger(__name__)

SCHLUSS_NAME = "Mara Lenz"

PERSONA = f"""\
Du bist {SCHLUSS_NAME}, Schlussredakteurin eines Wissensmagazins, das auf
Instagram erscheint. Du hast vorher bei einem großen Wissenschaftsmagazin
gearbeitet und weißt, wie ein Beitrag aussehen und klingen muss, damit
Leser ihn ernst nehmen und trotzdem gern lesen.

Du siehst den fertigen Beitrag zum ersten Mal: alle Bilder, so wie sie
im Feed erscheinen, und die Bildunterschrift. Die Fakten sind geprüft -
das ist nicht deine Aufgabe, und du fügst keine hinzu. Deine Aufgabe
ist, ob der Beitrag gut ist, und wenn nicht, ihn mit wenigen genauen
Änderungen besser zu machen.

# Woran du misst

Sprache: Klingt es wie ein gutes Magazin oder wie eine Maschine?
Verräterisch sind künstliche Spannung ("Doch dann geschah etwas
Unglaubliches"), Füllwörter, Superlative ohne Grund, Großbuchstaben zur
Betonung, Floskeln aus den sozialen Medien, Sätze, die nichts sagen.

Roter Faden: Erzählen die Bilder nacheinander eine Geschichte, die man
ohne Bildunterschrift versteht? Steht etwas doppelt? Fehlt der Schritt,
der das Ganze verständlich macht? Trägt jedes Bild etwas Eigenes?

Bild und Text: Zeigt das Foto, wovon der Satz darunter spricht? Steht
auf einem Bild ein Satz, der zu einem anderen Bild gehört?

Gestaltung: Ist alles gut lesbar? Ist ein Text zu lang für sein Bild?
Wiederholt sich ein Foto?

Gesamtwirkung: Würde eine professionelle Redaktion das so
veröffentlichen?

# Was du ändern darfst

Nur Texte, nur umformulieren oder kürzen - höchstens vier Änderungen,
die wichtigsten zuerst. Keine neue Tatsache, keine neue Zahl, kein neuer
Name. Ein Bildtext bleibt kurz: auf dem ersten Bild höchstens sieben
Wörter, auf den anderen höchstens vierzehn. Wenn der Beitrag gut ist,
änderst du nichts - eine Änderung um der Änderung willen macht ihn
nicht besser.

`alt` ist der Text genau so, wie er jetzt dasteht, damit er gefunden
wird. Bei der Bildunterschrift (stelle 0) ein Satz oder Absatz daraus,
wörtlich."""


class Aenderung(BaseModel):
    stelle: int = Field(
        description="1 = erstes Bild, 2 und folgende = die Karten, 0 = Bildunterschrift"
    )
    alt: str = Field(description="Der Text genau so, wie er jetzt dasteht")
    neu: str = Field(description="Der bessere Text - ohne neue Tatsache")
    grund: str = Field(description="Warum, in einem Satz")


class Schlussbericht(BaseModel):
    sprache: int = Field(ge=1, le=5, description="1 maschinell bis 5 wie ein gutes Magazin")
    roter_faden: int = Field(ge=1, le=5)
    bild_und_text: int = Field(ge=1, le=5)
    gestaltung: int = Field(ge=1, le=5)
    gesamt: int = Field(ge=1, le=5, description="Würde eine Redaktion das veröffentlichen?")
    staerke: str = Field(description="Was gut ist, in einem Satz")
    aenderungen: list[Aenderung] = Field(default_factory=list, max_length=4)
    lernpunkt: str = Field(
        default="",
        description=(
            "Ein Fehler, der beim Schreiben grundsätzlich vermieden werden "
            "sollte - als Regel für die nächsten Beiträge, in einem Satz. "
            "Leer, wenn es keinen gibt."
        ),
    )


def kontaktbogen(bilder: list[Path], ziel: Path, *, breite_je: int = 300) -> Path:
    """Alle Bilder des Beitrags nebeneinander auf einem Blatt, nummeriert.

    So sieht die Redaktion die Reihe wie im Feed: ob sie zusammenpasst,
    ob sich etwas wiederholt. Klein genug, dass das Ansehen wenig kostet,
    groß genug, dass sich die Schrift lesen lässt.
    """
    from PIL import ImageDraw

    from ..imaging.gestalt import schrift

    hoehe_je = int(breite_je * 1.25)
    spalten = min(len(bilder), 4)
    reihen = (len(bilder) + spalten - 1) // spalten
    blatt = Image.new("RGB", (spalten * (breite_je + 12) + 12, reihen * (hoehe_je + 48) + 12),
                      (235, 235, 235))
    zeichnung = ImageDraw.Draw(blatt)
    font = schrift("text_fett", 22)
    for nummer, pfad in enumerate(bilder, start=1):
        reihe, spalte = divmod(nummer - 1, spalten)
        x, y = 12 + spalte * (breite_je + 12), 12 + reihe * (hoehe_je + 48)
        zeichnung.text((x, y), f"Bild {nummer}", font=font, fill=(20, 20, 20))
        with Image.open(pfad) as bild:
            blatt.paste(bild.convert("RGB").resize((breite_je, hoehe_je)), (x, y + 32))
    ziel.parent.mkdir(parents=True, exist_ok=True)
    blatt.save(ziel, "JPEG", quality=82)
    return ziel


def _texte(draft: PostDraft) -> str:
    zeilen = [f"Bild 1 (Titel): {draft.bildtext}"]
    if draft.visual.subline.strip():
        zeilen.append(f"   Unterzeile: {draft.visual.subline}")
    for nummer, karte in enumerate(draft.karten[:4], start=2):
        zeile = f"Bild {nummer} ({karte.layout}, Rolle {karte.rolle}): {karte.text}"
        if karte.zahl:
            zeile += f" [große Zahl: {karte.zahl}]"
        if karte.erklaerung:
            zeile += f" - {karte.erklaerung}"
        zeilen.append(zeile)
    zeilen.append("Letztes Bild: Abschlusskarte mit Quelle, wird automatisch erzeugt.")
    return "\n".join(zeilen)


def schlussredaktion(
    brain: Brain,
    *,
    draft: PostDraft,
    bogen: Path,
    modell: str | None = None,
) -> Schlussbericht:
    bericht = brain.structured(
        schema=Schlussbericht,
        system=PERSONA,
        label="Schlussredaktion",
        task="research",
        modell=modell,
        bild=bogen,
        prompt=with_context(
            "# Die Bilder\nAngehängt: alle Bilder des Beitrags in ihrer Reihenfolge, nummeriert.",
            f"# Die Texte auf den Bildern\n{_texte(draft)}",
            f"# Die Bildunterschrift\n{draft.caption}\n\n{draft.call_to_action}",
            "# Auftrag\nBewerte den Beitrag und nenne die Änderungen, die ihn am meisten "
            "verbessern - oder keine, wenn er gut ist.",
        ),
    )
    log.info(
        "Schlussredaktion: gesamt %s/5, %s Änderungen", bericht.gesamt, len(bericht.aenderungen)
    )
    return bericht


__all__ = ["Aenderung", "Schlussbericht", "kontaktbogen", "schlussredaktion"]
