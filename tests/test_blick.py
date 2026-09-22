"""Hinsehen, bevor ein Bild in den Beitrag kommt.

Kein Test hier fragt ein Modell. Das ist keine Luecke, sondern der Sinn:
Eine Bildfrage kostet Geld, und was sich ohne sie pruefen laesst - die
Aufbereitung, das Lesen der Antwort, die Wirkung auf die Auswahl, das
Verhalten bei einem Ausfall - ist alles, was hier schiefgehen kann.
Ob das Modell ein Feuerwerk erkennt, entscheidet sich nicht im Test.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from insta_agent.imaging.blick import (
    FRAGEBREITE,
    UNGEPRUEFT,
    blickfaktor,
    lies_antwort,
    verkleinere_zur_frage,
)


def test_ein_grosses_bild_geht_klein_hinaus(tmp_path):
    """Die Frage ist "Tiefseetier oder Feuerwerk" - dafuer reichen 512 Pixel.

    In voller Groesse zu fragen kostet rund das Zehnfache und beantwortet
    dieselbe Frage nicht besser.
    """
    pfad = tmp_path / "gross.png"
    Image.new("RGB", (3200, 2000), (40, 80, 120)).save(pfad)

    daten, typ = verkleinere_zur_frage(pfad)

    assert typ == "image/jpeg"
    with Image.open(io.BytesIO(base64.standard_b64decode(daten))) as klein:
        assert klein.width == FRAGEBREITE
        # Das Seitenverhaeltnis bleibt - ein gezerrtes Bild zu beurteilen
        # waere schwerer, nicht leichter.
        assert abs(klein.height - FRAGEBREITE * 2000 / 3200) <= 1


def test_ein_kleines_bild_wird_nicht_hochgerechnet(tmp_path):
    pfad = tmp_path / "klein.png"
    Image.new("RGB", (300, 200), (40, 80, 120)).save(pfad)

    daten, _ = verkleinere_zur_frage(pfad)
    with Image.open(io.BytesIO(base64.standard_b64decode(daten))) as klein:
        assert klein.size == (300, 200)


def test_die_antwort_wird_nachsichtig_gelesen():
    """An der Form zu scheitern waere die teuerste Art von Fehler.

    Die Frage ist dann bezahlt und das Ergebnis weg.
    """
    assert lies_antwort("7|Ein Tiefseefisch am Grund")[0] == 7
    assert lies_antwort("1 - Feuerwerk ueber Wasser")[0] == 1
    assert lies_antwort("  3 : Seeloewe auf Felsen")[0] == 3
    assert lies_antwort("10")[0] == 10


def test_eine_unverstaendliche_antwort_wertet_nicht_ab():
    """Eine Pruefung ohne Ergebnis ist kein Urteil ueber das Bild."""
    punkte, _ = lies_antwort("keine Ahnung, was das sein soll")
    assert punkte == UNGEPRUEFT
    assert blickfaktor(punkte) == 1.0


def test_ein_uebergrosser_wert_wird_gedeckelt():
    assert lies_antwort("99|irgendwas")[0] == 10


def test_der_faktor_trennt_das_thema_vom_zufallstreffer():
    """Der Fall, der dreimal hintereinander schiefgegangen ist.

    Ein Feuerwerk mit einem Punkt darf gegen ein Tiefseefoto mit neun
    keine Aussicht mehr haben - auch dann nicht, wenn das Feuerwerk
    schaerfer, groesser und weiter vorn im Archiv steht.
    """
    assert blickfaktor(9) / blickfaktor(1) > 2.5


def test_ganz_unten_bleibt_ein_rest():
    """Wenn jedes Bild durchfaellt, ist das schlechteste immer noch
    besser als gar keins - dann wird sonst gemalt, und gemalt ist
    derzeit schlechter als jede echte Aufnahme."""
    assert blickfaktor(0) > 0.1


# --- Was der Blick in der Auswahl bewirkt ---------------------------------


def _fund(seite, breite, hoehe):
    from insta_agent.imaging.echtbild import Fundbild

    return Fundbild(
        url=f"https://u.example/{seite}",
        pfad=None,
        lizenz="CC0",
        urheber="",
        seite=seite,
        breite=breite,
        hoehe=hoehe,
    )


def _suche_vorbereiten(monkeypatch, treffer):
    from insta_agent.imaging import echtbild

    monkeypatch.setattr(echtbild, "suche_bilder", lambda *a, **k: treffer)

    def lade(bild, ziel, **_):
        Image.new("RGB", (240, 160), (70, 90, 110)).save(ziel)
        bild.pfad = ziel
        return bild

    monkeypatch.setattr(echtbild, "hole_bild", lade)
    monkeypatch.setattr(
        "insta_agent.imaging.fotoprobe.wirkt_wie_foto", lambda _p: (True, "")
    )
    monkeypatch.setattr(
        "insta_agent.imaging.schaerfe.schaerfewert", lambda *a, **k: 0.9
    )
    return echtbild


def test_der_blick_dreht_die_auswahl(tmp_path, monkeypatch):
    """Das Feuerwerk steht vorn, ist groesser und schaerfer - und verliert.

    Bei "deep sea creature" hat es dreimal gewonnen: einmal ueber die
    Form, einmal ueber die Schaerfe, einmal ueber den Rang. Jedes dieser
    Merkmale steht neben dem Bild. Was darauf zu sehen ist, wusste keines.
    """
    feuerwerk = _fund("Deep Sea Legend following Fireworks.jpg", 2400, 1600)
    meeresgrund = _fund("Nur04507.jpg", 1804, 1176)
    echtbild = _suche_vorbereiten(monkeypatch, [feuerwerk, meeresgrund])

    urteile = {
        "Deep Sea Legend following Fireworks.jpg": (1, "Feuerwerk ueber Wasser"),
        "Nur04507.jpg": (9, "Tiefseefisch am Meeresgrund"),
    }

    # Ohne Hinsehen gewinnt das Feuerwerk - vorn im Archiv und groesser.
    ohne = echtbild.finde_und_hole("deep sea creature", tmp_path / "a.jpg")
    assert ohne is not None
    assert "Fireworks" in ohne.seite

    # Mit Hinsehen gewinnt die Aufnahme vom Meeresgrund.
    for bild in (feuerwerk, meeresgrund):
        bild.pfad, bild.grund, bild.gesehen = None, "", ""

    mit = echtbild.finde_und_hole(
        "deep sea creature",
        tmp_path / "b.jpg",
        blick=lambda pfad: urteile[_wessen(pfad, urteile)],
    )
    assert mit is not None
    assert mit.seite == "Nur04507.jpg"


def _wessen(pfad, urteile):
    """Welcher Treffer gerade auf der Platte liegt.

    Die Zwischendateien heissen nach ihrem Platz, nicht nach ihrem Titel -
    also wird am Dateinamen abgelesen, der wievielte es ist.
    """
    namen = list(urteile)
    stelle = int(str(pfad).rsplit("-v", 1)[1].split(".")[0])
    return namen[stelle]


def test_ein_ausfall_beim_hinsehen_kostet_kein_bild(tmp_path, monkeypatch):
    """Wenn die Frage scheitert, bleibt die Suche, wie sie ohne sie waere.

    Alles andere hiesse: Ein Netzausfall beim Bildansehen laesst den
    Beitrag ohne Foto dastehen - und dann wird gemalt.
    """
    echtbild = _suche_vorbereiten(monkeypatch, [_fund("gut.jpg", 2400, 1600)])

    def geht_schief(_pfad):
        raise RuntimeError("Netz weg")

    gefunden = echtbild.finde_und_hole(
        "x", tmp_path / "ziel.jpg", blick=geht_schief
    )
    assert gefunden is not None
    assert gefunden.seite == "gut.jpg"


def test_ohne_thema_wird_nicht_gefragt():
    """Eine Frage ohne Vergleichsmassstab kostet Geld und bringt nichts."""
    from insta_agent.runner import Agent

    class Attrappe:
        _bilder_heute_aus = ""
        brain = object()

        class settings:
            class posting:
                bilder_ansehen = True

    assert Agent._blick_auf(Attrappe(), "") is None
    assert Agent._blick_auf(Attrappe(), "   ") is None
    assert Agent._blick_auf(Attrappe(), "deep sea") is not None


def test_abgeschaltet_wird_nicht_gefragt():
    from insta_agent.runner import Agent

    class Attrappe:
        _bilder_heute_aus = ""
        brain = object()

        class settings:
            class posting:
                bilder_ansehen = False

    assert Agent._blick_auf(Attrappe(), "deep sea") is None


# --- Die Frage selbst, mit einem Doppelgaenger statt eines Modells --------


class _Antwort:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.stop_reason = stop_reason
        self.usage = type("U", (), {"input_tokens": 420, "output_tokens": 18})()


class _Buchhaltung:
    """Nimmt entgegen, was gebucht wird, und merkt es sich."""

    def __init__(self):
        self.buchungen = []

    def charge(self, amount_usd, category, note="", meta=None):
        self.buchungen.append((amount_usd, category, note, meta))


class _Modellattrappe:
    """Antwortet immer dasselbe - oder wirft, wenn das die Probe ist."""

    def __init__(self, antwort):
        self._antwort = antwort
        self.gefragt = []
        self.messages = self

    def create(self, **kwargs):
        if isinstance(self._antwort, Exception):
            raise self._antwort
        self.gefragt.append(kwargs)
        return self._antwort


def _gehirn(antwort):
    from insta_agent.config import LLMConfig
    from insta_agent.llm import Brain

    kasse = _Buchhaltung()
    gehirn = Brain(LLMConfig(), kasse)
    doppel = _Modellattrappe(antwort)
    gehirn.client = doppel
    return gehirn, doppel, kasse


def test_die_bildfrage_geht_ans_guenstigste_modell(tmp_path):
    """Ein Bild anzusehen ist keine Aufgabe fuer das teure Modell.

    Die Frage ist "zeigt das die Sache oder nicht" - dafuer reicht das
    kleinste, und der Preisunterschied ist der fuenffache.
    """
    pfad = tmp_path / "bild.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(pfad)

    gehirn, doppel, kasse = _gehirn(_Antwort("9|Tiefseefisch am Meeresgrund"))
    punkte, was = gehirn.beurteile_bild(pfad, "deep sea creature")

    assert (punkte, was) == (9, "Tiefseefisch am Meeresgrund")
    assert doppel.gefragt[0]["model"] == gehirn.config.cheap_model
    inhalt = doppel.gefragt[0]["messages"][0]["content"]
    assert inhalt[0]["type"] == "image"
    assert "deep sea creature" in inhalt[1]["text"]


def test_die_bildfrage_wird_gebucht(tmp_path):
    """Sonst steht am Monatsende ein Betrag da, den niemand zuordnen kann."""
    pfad = tmp_path / "bild.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(pfad)

    gehirn, _, kasse = _gehirn(_Antwort("4|Irgendein Meer"))
    gehirn.beurteile_bild(pfad, "deep sea creature")

    assert len(kasse.buchungen) == 1
    betrag, kategorie, vermerk, meta = kasse.buchungen[0]
    assert betrag > 0
    assert kategorie == "llm"
    # Das Modell gehoert in die Buchung, sonst laesst sich hinterher
    # nicht sagen, was das Hinsehen gekostet hat.
    assert meta["model"] == gehirn.config.cheap_model


def test_ein_fehler_bei_der_bildfrage_bleibt_folgenlos(tmp_path):
    """Lieber ein unbesehenes Foto als gar keines."""
    from insta_agent.imaging.blick import UNGEPRUEFT

    pfad = tmp_path / "bild.png"
    Image.new("RGB", (800, 600), (30, 60, 90)).save(pfad)

    gehirn, _, kasse = _gehirn(RuntimeError("Netz weg"))
    assert gehirn.beurteile_bild(pfad, "x") == (UNGEPRUEFT, "")


def test_eine_fehlende_datei_kostet_nichts(tmp_path):
    """Es waere bezahlt und ohne Ergebnis - also wird gar nicht gefragt."""
    from insta_agent.imaging.blick import UNGEPRUEFT

    gehirn, doppel, kasse = _gehirn(_Antwort("9|egal"))
    assert gehirn.beurteile_bild(tmp_path / "gibtsnicht.png", "x") == (UNGEPRUEFT, "")
    assert doppel.gefragt == []


# --- Eine Nachbildung ist nicht die Sache selbst --------------------------


def test_die_frage_nennt_nachbildungen_ausdruecklich():
    """Der Fehler, den erst der erste echte Durchlauf gezeigt hat.

    Das Modell sah richtig hin und beschrieb es richtig - "Leuchtende
    Kunstinstallation einer Qualle mit Tentakeln" - und gab trotzdem
    9 von 10. Es bewertete "sieht aus wie das Thema" statt "zeigt die
    Sache selbst".

    Der Beitrag soll zeigen, worum es geht. Eine Lichtinstallation in
    Quallenform zeigt eine Lichtinstallation.
    """
    from insta_agent.imaging.blick import FRAGE

    klein = FRAGE.casefold()
    for wort in ("kunstinstallation", "nachbildung", "modell", "zeichnung"):
        assert wort in klein
    assert "hoechstens 3" in klein


def test_eine_nachbildung_verliert_gegen_die_sache_selbst():
    """Drei Punkte gegen sieben muessen die Entscheidung drehen.

    Nach den ersten Zahlen taten sie das nicht deutlich genug: Die
    Installation stand vorn im Archiv, war groesser und schaerfer.
    """
    from insta_agent.imaging.blick import blickfaktor
    from insta_agent.imaging.echtbild import guete, rangfaktor, schaerfefaktor
    from insta_agent.imaging.schaerfe import SCHARF_GENUG

    installation = (
        guete(1280, 2276)
        * rangfaktor(1, geprueft=True)
        * schaerfefaktor(0.66, SCHARF_GENUG)
        * blickfaktor(3)
    )
    echte_aufnahme = (
        guete(1804, 1176)
        * rangfaktor(2, geprueft=True)
        * schaerfefaktor(0.56, SCHARF_GENUG)
        * blickfaktor(7)
    )
    assert echte_aufnahme > installation * 1.4


def test_der_rang_zaehlt_weniger_wenn_jemand_hingesehen_hat():
    """Der Rang war immer nur ein Ersatz dafuer, dass niemand hinsah.

    Liegt ein wirkliches Urteil vor, ist die Vermutung, die eine
    Volltextsuche aus Dateinamen ableitet, nur noch ein
    Gleichstandsbrecher.
    """
    from insta_agent.imaging.echtbild import rangfaktor

    assert rangfaktor(4, geprueft=True) > rangfaktor(4)
    # Ganz verschwinden darf er nicht - bei Gleichstand gewinnt das
    # vordere Bild, weil es wahrscheinlicher zum Thema gehoert.
    assert rangfaktor(4, geprueft=True) < rangfaktor(0, geprueft=True)


def test_ohne_urteil_bleibt_der_rang_so_stark_wie_vorher():
    """Sonst waere abgeschaltetes Hinsehen zugleich ein schwaecherer Rang -
    und niemand haette das entschieden."""
    from insta_agent.imaging.echtbild import rangfaktor

    assert rangfaktor(3) == 1.0 / (1.0 + 0.30 * 3)
