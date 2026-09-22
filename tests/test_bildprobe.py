"""Erst schauen, ob sich die Sache zeigen laesst - dann schreiben.

Aus dem Beitrag ueber die leuchtende Koralle: Stoffsuche, Text und
Bildsprache waren bezahlt, als sich herausstellte, dass es von dieser
Art kein freies Foto gibt. Der Beitrag bekam einen Frosch, eine Treppe
und einen Krill. Der Betreiber: "Ja, bau das mit dem freien Foto ein."
"""

from __future__ import annotations

from pathlib import Path

import insta_agent.runner as runner_modul
from insta_agent.runner import BILD_VOM_FUND, Agent, Bildprobe


class _Fund:
    def __init__(self, titel, reiz=5, bildkraft=4):
        self.titel = titel
        self.reiz = reiz
        self.bildkraft = bildkraft
        self.beleglage = "gemeldet"
        self.verworfen = []

    @property
    def taugt(self):
        return self.reiz >= 4 and self.bildkraft >= 3


class _Bericht:
    def __init__(self):
        self.steps = []


def _agent(tmp_path, *, gefunden: dict[str, tuple[Path | None, int | None]]):
    """Ein Agent, dessen Bildsuche vorher festgelegt ist: Titel -> (Bild, Stufe)."""
    agent = object.__new__(Agent)

    class Einstellungen:
        media_dir = tmp_path

        class posting:
            stoff_noetig = True
            bildformat = "feed"
            bilder_ansehen = True

    class Kasse:
        class _Stand:
            mode = runner_modul.Mode.NORMAL

        def state(self):
            return self._Stand()

    class Laden:
        def letzte_funde(self, limit):
            return []

        def letzte_gebiete(self, limit):
            return []

        def log(self, *a):
            pass

        def get_model(self, schluessel, art):
            return None

    agent.settings = Einstellungen()
    agent.treasury = Kasse()
    agent.store = Laden()
    agent.brain = None
    agent._modell = lambda rolle: None
    agent._person = lambda rolle: None
    agent.suchen = []

    def echtes_bild(fund, basis, report):
        agent.suchen.append(fund.titel)
        bild, stufe = gefunden[fund.titel]
        agent._letzte_bildstufe = stufe
        agent._quellbilder = []
        agent._bildthema = fund.titel
        return bild, ("Bild: X · CC BY" if bild else "")

    agent._echtes_bild = echtes_bild
    return agent


def _stoffsuche(monkeypatch, *funde):
    gefragt = []
    reihe = list(funde)

    def finde_stoff(brain, **k):
        gefragt.append(k)
        return reihe.pop(0)

    monkeypatch.setattr(runner_modul, "finde_stoff", finde_stoff)
    return gefragt


def test_mit_foto_vom_fund_wird_nicht_nachgesetzt(tmp_path, monkeypatch):
    koralle = _Fund("Koralle")
    gefragt = _stoffsuche(monkeypatch, koralle)
    agent = _agent(tmp_path, gefunden={"Koralle": (tmp_path / "k.jpg", BILD_VOM_FUND)})

    assert agent._suche_stoff(_Bericht()) is koralle
    assert len(gefragt) == 1


def test_ohne_freies_foto_wird_einmal_nachgesetzt_mit_grund(tmp_path, monkeypatch):
    koralle = _Fund("Koralle")
    schatz = _Fund("Goldschatz")
    gefragt = _stoffsuche(monkeypatch, koralle, schatz)
    agent = _agent(
        tmp_path,
        gefunden={
            "Koralle": (None, None),
            "Goldschatz": (tmp_path / "g.jpg", BILD_VOM_FUND),
        },
    )
    bericht = _Bericht()

    assert agent._suche_stoff(bericht) is schatz
    assert len(gefragt) == 2
    # Der zweite Anlauf weiss, warum der erste nicht reichte.
    assert gefragt[1]["nachsetzen"] is koralle
    assert "kein frei nutzbares Foto" in gefragt[1]["grund"]
    assert any("Kein freies Foto" in s for s in bericht.steps)


def test_ein_bild_das_nur_zum_thema_passt_reicht_nicht(tmp_path, monkeypatch):
    """Ein Archivbild mit 5 von 10 zeigt nicht die Sache, nur ihr Umfeld."""
    koralle = _Fund("Koralle")
    schatz = _Fund("Goldschatz")
    _stoffsuche(monkeypatch, koralle, schatz)
    agent = _agent(
        tmp_path,
        gefunden={
            "Koralle": (tmp_path / "k.jpg", 5),
            "Goldschatz": (tmp_path / "g.jpg", 9),
        },
    )
    assert agent._suche_stoff(_Bericht()) is schatz


def test_ist_der_zweite_nicht_besser_bleibt_der_erste(tmp_path, monkeypatch):
    koralle = _Fund("Koralle")
    wurm = _Fund("Grauer Wurm")
    _stoffsuche(monkeypatch, koralle, wurm)
    agent = _agent(tmp_path, gefunden={"Koralle": (None, None), "Grauer Wurm": (None, None)})
    bericht = _Bericht()

    assert agent._suche_stoff(bericht) is koralle
    assert any("es bleibt beim ersten" in s for s in bericht.steps)


def test_hoechstens_ein_nachschlag_je_zyklus(tmp_path, monkeypatch):
    """Jede Runde kostet so viel wie die erste. War der erste Fund schon zu
    schwach und wurde nachgesetzt, gibt es keine dritte Runde fuers Foto."""
    schwach = _Fund("Schwach", reiz=3)
    koralle = _Fund("Koralle")
    gefragt = _stoffsuche(monkeypatch, schwach, koralle)
    agent = _agent(tmp_path, gefunden={"Koralle": (None, None), "Schwach": (None, None)})

    assert agent._suche_stoff(_Bericht()) is koralle
    assert len(gefragt) == 2


def test_das_bild_der_probe_wird_spaeter_verwendet_und_nicht_neu_gesucht(tmp_path, monkeypatch):
    """Sonst kostet das Hinsehen doppelt."""
    from PIL import Image

    koralle = _Fund("Koralle")
    _stoffsuche(monkeypatch, koralle)
    bild = tmp_path / "k.jpg"
    Image.new("RGB", (1200, 1500), (20, 60, 90)).save(bild)
    agent = _agent(tmp_path, gefunden={"Koralle": (bild, BILD_VOM_FUND)})
    agent._suche_stoff(_Bericht())
    assert agent.suchen == ["Koralle"]

    class Entwurf:
        bildtext = "Diese Koralle leuchtet nur, wenn man sie berührt"

        class visual:
            pass

    monkeypatch.setattr(runner_modul, "lege_hook_auf", lambda roh, ziel, **k: ziel)

    class Ich:
        handle = "erstfund"

    fertig, roh = agent._erzeuge_bild(Entwurf(), "b", Ich(), _Bericht(), koralle)

    assert roh == bild
    assert agent.suchen == ["Koralle"]  # nicht ein zweites Mal
    assert agent._bildproben == {}


def test_ungeprueft_gilt_ein_gefundenes_foto():
    """Ist Hinsehen abgeschaltet, laesst sich nichts beurteilen."""
    assert Bildprobe(Path("x"), "", [], "", -1).zeigt_die_sache
    assert not Bildprobe(None, "", [], "", None).zeigt_die_sache
    assert not Bildprobe(Path("x"), "", [], "", 6).zeigt_die_sache
    assert Bildprobe(Path("x"), "", [], "", 7).zeigt_die_sache
