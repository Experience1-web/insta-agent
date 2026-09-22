"""Was ein Beitrag erzaehlen muss - damit er nicht zusammengewuerfelt wirkt.

Aus dem Beitrag ueber die leuchtende Koralle, den der Betreiber zu Recht
"konzeptlos" nannte: Auf dem ersten Bild stand "Bei Beruehrung antwortet
sie mit 515 Nanometern" ueber einem Frosch. Dann "Corallizoanthus aureus,
2025 beschrieben", dann "Licht nur auf Reiz, nicht dauerhaft" ueber einem
Krill. Jede Karte hat eine Tatsache getragen - so stand es im Auftrag -,
und keine hat jemandem etwas gesagt, der nicht Meeresbiologe ist.

Die Tests hier pruefen den Auftrag, nicht das Modell. Ob das Modell ihn
befolgt, zeigt erst ein Zyklus. Aber verschwindet eine dieser Regeln
unbemerkt aus dem Auftrag, faellt das hier auf.
"""

from __future__ import annotations

from insta_agent.brain.content import KARUSSELL


def test_eine_wichtige_tatsache_je_karte():
    """So will es der Betreiber: die Fakten auf die Bilder verteilt."""
    assert "eine je\nKarte" in KARUSSELL or "eine je Karte" in KARUSSELL
    assert "genau eine der wichtigen Tatsachen" in KARUSSELL


def test_die_karten_erzaehlen_der_reihe_nach():
    assert "Reihenfolge erzaehlt eine Geschichte" in KARUSSELL.replace("\n", " ")


def test_jede_karte_muss_ohne_vorwissen_verstaendlich_sein():
    flach = KARUSSELL.replace("\n", " ")
    assert "jemand verstehen, der nichts darueber weiss" in flach
    # Die drei Fehler aus dem Koralle-Beitrag, ausdruecklich benannt.
    assert "515 Nanometer" in flach
    assert "Auf Reiz" in flach
    assert "lateinischer Name steht nie allein auf einer Karte" in flach


def test_die_bilder_zeigen_die_sache_und_nicht_ein_wort_aus_dem_text():
    flach = KARUSSELL.replace("\n", " ")
    assert "Die Bilder zeigen die Sache, um die es geht" in flach
    assert "Treppe" in flach


def test_der_hook_nennt_die_sache_beim_namen():
    from pathlib import Path

    quelle = Path("insta_agent/brain/content.py").read_text(encoding="utf-8")
    assert "ohne jedes Vorwissen sofort verständlich" in quelle
    assert 'Gut: "Diese Koralle leuchtet nur, wenn man sie berührt"' in quelle


def test_das_kartenmodell_verlangt_keine_nackten_zahlen_mehr():
    """Die Feldbeschreibung liest das Modell bei jedem Aufruf mit."""
    from insta_agent.models import Karte

    beschreibung = Karte.model_fields["text"].description
    assert "genau eine der wichtigen Tatsachen" in beschreibung
    assert "ohne Vorwissen" in beschreibung
    assert "ein Jahr, ein Name" not in beschreibung


def test_kartenbilder_werden_gegen_den_fund_beurteilt(tmp_path, monkeypatch):
    """Nicht gegen das Suchwort der Karte - sonst passt die Treppe zu "cave"."""
    import insta_agent.imaging.echtbild as echtbild_modul
    from insta_agent.imaging.echtbild import KARTENBLICK
    from insta_agent.runner import Agent

    aufrufe = []

    def finde(suchwort, ziel, **k):
        aufrufe.append((suchwort, k))
        return None

    monkeypatch.setattr(echtbild_modul, "finde_und_hole", finde)

    agent = object.__new__(Agent)

    class Einstellungen:
        media_dir = tmp_path

        class posting:
            bildformat = "feed"
            bilder_ansehen = True

    agent.settings = Einstellungen()
    agent.bildgenerator = None
    agent._bilder_heute_aus = ""
    agent._bildthema = "Corallizoanthus aureus - Leuchtende Koralle in einer Unterwasserhöhle"
    gefragt = []

    class Gehirn:
        def beurteile_bild(self, pfad, thema):
            gefragt.append(thema)
            return 8, "passt"

    agent.brain = Gehirn()

    class Karte:
        bildsuche = "cave"
        bildwunsch = ""

    agent._karte_rohbild(Karte(), "test", 2)

    suchwort, k = aufrufe[0]
    assert suchwort == "cave"
    assert k["mindestblick"] == KARTENBLICK
    k["blick"](tmp_path / "x.jpg")
    assert gefragt == [agent._bildthema]


def test_nur_die_tatsachen_die_man_weitererzaehlen_wuerde():
    """Der Betreiber: nicht irgendwelche Fakten, sondern die interessanten."""
    flach = KARUSSELL.replace("\n", " ")
    assert "Aber nur die Tatsachen, die sich interessant anhoeren" in flach
    assert "beim Abendessen weitererzaehlen" in flach
    # Name und Jahr sind der Beleg, nicht die Geschichte.
    assert "Aktenvermerk" in flach
