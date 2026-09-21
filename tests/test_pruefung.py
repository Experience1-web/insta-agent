"""Die Endprüfung ist die einzige Kontrolle vor der Freigabe.

Sie muss deshalb selbst streng geprüft sein: Was sie an das Modell
schickt, was sie mit der Antwort macht, und vor allem, was passiert,
wenn sie ausfällt. Eine Prüfung, die still scheitert und den Beitrag
trotzdem durchwinkt, ist schlimmer als gar keine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insta_agent.brain.pruefung import (
    PRUEFER_NAME,
    PRUEFER_PERSONA,
    _zu_pruefen,
    pruefe_beitrag,
)
from insta_agent.models import Befund, Pruefbericht
from test_cycle import _entwurf, _identitaet


class FakeBrain:
    """Merkt sich den Aufruf und gibt einen vorbereiteten Bericht zurück."""

    def __init__(self, bericht: Pruefbericht | None = None, quellen: list[str] | None = None):
        self.bericht = bericht or Pruefbericht(urteil="freigabe", zusammenfassung="ok")
        self.letzte_quellen = quellen or []
        self.aufruf: dict = {}
        self.suchbudget = 5

    def structured(self, **kwargs):
        self.aufruf = kwargs
        return self.bericht


def _pruefe(brain, **kwargs):
    return pruefe_beitrag(brain, identity=_identitaet(), draft=_entwurf(), **kwargs)


# --- Was geprüft wird ------------------------------------------------------


def test_alles_mit_tatsachen_geht_mit(draft):
    """Bild, Unterschrift und erster Kommentar - überall kann eine Zahl stehen."""
    text = _zu_pruefen(draft)

    assert draft.bildtext in text
    assert draft.caption in text
    assert draft.first_comment_prompt in text


def test_der_bildprompt_geht_nicht_mit(draft):
    """Der ist eine Malanweisung, keine Behauptung über die Welt."""
    assert draft.image_generation_prompt not in _zu_pruefen(draft)


def test_hashtags_gehen_nicht_mit(draft):
    """Prüfbar ist, was behauptet wird - nicht, wie es gefunden wird."""
    draft.hashtags = ["unbelegbarestichwort"]

    assert "unbelegbarestichwort" not in _zu_pruefen(draft)


# --- Wer prüft, mit welchem Modell -----------------------------------------


def test_geprueft_wird_mit_dem_recherchemodell():
    """Prüfen ist Nachschlagen, keine kreative Arbeit - das teuerste Modell
    waere hier verschwendet."""
    brain = FakeBrain()

    _pruefe(brain)

    assert brain.aufruf["task"] == "research"


def test_die_pruefung_darf_nachschlagen():
    brain = FakeBrain()

    _pruefe(brain, mit_suche=True)

    assert brain.aufruf["web_search"] is True


def test_das_modell_laesst_sich_umstellen():
    """Der Betreiber soll die Rolle billiger oder besser machen koennen."""
    brain = FakeBrain()

    _pruefe(brain, modell="claude-haiku-4-5")

    assert brain.aufruf["modell"] == "claude-haiku-4-5"


def test_ohne_wahl_bleibt_es_bei_der_voreinstellung():
    brain = FakeBrain()

    _pruefe(brain)

    assert brain.aufruf["modell"] is None


def test_die_pruefung_hat_einen_eigenen_auftrag():
    """Wer den Beitrag geschrieben hat, ist der falsche, um ihn zu pruefen."""
    brain = FakeBrain()

    _pruefe(brain)

    from insta_agent.brain.prompts import PERSONA

    assert brain.aufruf["system"] != PERSONA
    assert brain.aufruf["system"] == PRUEFER_PERSONA
    assert PRUEFER_NAME in brain.aufruf["system"]


# --- Was mit der Antwort passiert -------------------------------------------


def test_der_pruefer_wird_vom_code_eingetragen_nicht_vom_modell():
    """Sonst koennte sich das Modell selbst ein schoeneres Zeugnis ausstellen."""
    brain = FakeBrain(
        Pruefbericht(urteil="freigabe", zusammenfassung="ok", geprueft_von="Der Chef persoenlich")
    )

    bericht = _pruefe(brain)

    assert bericht.geprueft_von == PRUEFER_NAME


def test_ob_gesucht_wurde_traegt_der_code_ein():
    """Das Modell darf nicht behaupten, es haette nachgeschlagen."""
    brain = FakeBrain(Pruefbericht(urteil="freigabe", zusammenfassung="ok", mit_suche=True))

    bericht = _pruefe(brain, mit_suche=False)

    assert bericht.mit_suche is False


def test_die_wirklich_aufgerufenen_quellen_kommen_dazu():
    brain = FakeBrain(
        Pruefbericht(urteil="freigabe", zusammenfassung="ok", quellen=["https://a.test"]),
        quellen=["https://b.test", "https://a.test"],
    )

    bericht = _pruefe(brain)

    assert bericht.quellen == ["https://a.test", "https://b.test"]


# --- Das Urteil -------------------------------------------------------------


def test_nur_freigabe_darf_raus():
    for urteil in ("nachbessern", "ablehnen"):
        bericht = Pruefbericht(urteil=urteil, zusammenfassung="x")
        assert not bericht.darf_raus
    assert Pruefbericht(urteil="freigabe", zusammenfassung="x").darf_raus


def test_beanstandet_zaehlt_alles_ausser_belegt():
    """Unbelegbar ist kein mildes Urteil - eine Zahl ohne Quelle zaehlt mit."""
    bericht = Pruefbericht(
        urteil="nachbessern",
        zusammenfassung="x",
        befunde=[
            Befund(behauptung="a", urteil="belegt", begruendung="-"),
            Befund(behauptung="b", urteil="unbelegbar", begruendung="-"),
            Befund(behauptung="c", urteil="ungenau", begruendung="-"),
            Befund(behauptung="d", urteil="falsch", begruendung="-"),
        ],
    )

    assert [b.behauptung for b in bericht.beanstandet] == ["b", "c", "d"]


# --- Im Zyklus --------------------------------------------------------------


def test_der_bericht_haengt_am_entwurf(agent_mit_doppel):
    """Sonst sieht der Betreiber bei der Freigabe nicht, was gefunden wurde."""
    import json

    agent = agent_mit_doppel
    agent.run_cycle()

    zeile = agent.store.pending_drafts()[0]
    bericht = json.loads(zeile["pruefung_json"])

    assert bericht["urteil"] == "freigabe"
    assert bericht["geprueft_von"] == PRUEFER_NAME


def test_ein_ausfall_der_pruefung_kostet_nicht_den_zyklus(agent_mit_doppel, monkeypatch):
    """Ein fehlender Bericht ist schlecht. Ein verlorener Tag ist schlimmer."""
    agent = agent_mit_doppel
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Suche kaputt")),
    )

    bericht = agent.run_cycle()

    assert bericht.halted_reason is None
    assert len(agent.store.pending_drafts()) == 1
    assert any("nicht geprüft" in s for s in bericht.steps)


def test_ein_ausfall_wird_nicht_als_geprueft_ausgegeben(agent_mit_doppel, monkeypatch):
    agent = agent_mit_doppel
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Suche kaputt")),
    )

    agent.run_cycle()

    assert agent.store.pending_drafts()[0]["pruefung_json"] is None


def test_im_autopilot_haelt_ein_schlechtes_urteil_den_beitrag_an(
    agent_mit_doppel, monkeypatch
):
    """Genau dafür ist die Prüfung da: Wo kein Mensch mehr hinsieht,
    entscheidet sie."""
    agent = agent_mit_doppel
    agent.settings.posting.freigabe_noetig = False
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: Pruefbericht(
            urteil="ablehnen",
            zusammenfassung="Die Zahl steht so nirgends.",
            befunde=[Befund(behauptung="25 Tage", urteil="falsch", begruendung="-")],
        ),
    )

    bericht = agent.run_cycle()

    assert agent.store.approved_drafts() == []
    assert any("angehalten" in s for s in bericht.steps)


def test_im_autopilot_geht_ein_sauberer_beitrag_weiter_raus(agent_mit_doppel):
    agent = agent_mit_doppel
    agent.settings.posting.freigabe_noetig = False

    agent.run_cycle()

    assert len(agent.store.approved_drafts()) == 1


def test_ohne_pruefung_laeuft_alles_wie_vorher(agent_mit_doppel):
    """Abschaltbar bleibt sie - aber nur ausdruecklich."""
    agent = agent_mit_doppel
    agent.settings.posting.pruefung_noetig = False

    agent.run_cycle()

    assert agent.store.pending_drafts()[0]["pruefung_json"] is None


@pytest.fixture
def draft():
    return _entwurf()


@pytest.fixture
def agent_mit_doppel(tmp_path, monkeypatch):
    """Ein vollständiger Agent, dessen Modellaufrufe von Doppeln bedient werden."""
    from insta_agent.config import EconomyConfig, LLMConfig, PostingConfig, Settings
    from insta_agent.runner import Agent
    from test_cycle import FakeBrain

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    settings = Settings(
        llm=LLMConfig(),
        economy=EconomyConfig(
            treasury_start_usd=5.0,
            low_balance_usd=1.0,
            halt_balance_usd=0.25,
            max_cost_per_cycle_usd=2.0,
        ),
        posting=PostingConfig(posts_per_day=1, live=False),
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )
    a = Agent(settings)
    yield a
    a.close()


# --- Kein Bild, keine Bildsprache -----------------------------------------


def test_ohne_kontingent_wird_die_bildsprache_nicht_mehr_bezahlt(agent_mit_doppel, monkeypatch):
    """Ihr Ergebnis ist ein Bildprompt. Ohne Bild waere das Arbeit fuer nichts."""
    agent = agent_mit_doppel
    agent.settings.posting.posts_per_day = 2

    from insta_agent.imaging.generator import KontingentErschoepft

    class LeeresKontingent:
        def erzeuge(self, prompt, ziel):
            raise KontingentErschoepft("Fuer heute aufgebraucht")

    agent.bildgenerator = LeeresKontingent()
    agent.settings.bild.token = "probe"

    bericht = agent.run_cycle()

    uebersprungen = [s for s in bericht.steps if "Bildsprache uebersprungen" in s]
    assert uebersprungen, "der zweite Beitrag soll sie nicht mehr aufrufen"
    # Der erste Beitrag wird noch gestaltet - vorher weiss es niemand.
    assert any("Bildsprache: Niveau" in s for s in bericht.steps)


def test_ein_gewoehnlicher_bildfehler_haelt_die_bildsprache_nicht_auf(agent_mit_doppel):
    """Ein Aussetzer ist kein Tageslimit - beim naechsten Bild kann es klappen."""
    agent = agent_mit_doppel
    agent.settings.posting.posts_per_day = 2

    class WackligerDienst:
        def erzeuge(self, prompt, ziel):
            raise RuntimeError("Netz kurz weg")

    agent.bildgenerator = WackligerDienst()
    agent.settings.bild.token = "probe"

    bericht = agent.run_cycle()

    assert not [s for s in bericht.steps if "Bildsprache uebersprungen" in s]
    assert len([s for s in bericht.steps if "Bildsprache: Niveau" in s]) == 2


# --- Nachbessern statt vorlegen -------------------------------------------


def _mit_befund(urteil="ablehnen"):
    return Pruefbericht(
        urteil=urteil,
        zusammenfassung="Die Zahl steht so nirgends.",
        befunde=[Befund(behauptung="12 von 1.000", urteil="falsch", begruendung="-")],
    )


def test_ein_beanstandeter_entwurf_wird_selbst_nachgebessert(agent_mit_doppel, monkeypatch):
    """Sonst legt er dem Betreiber falsche Zahlen vor und laesst ihn machen."""
    urteile = [_mit_befund(), Pruefbericht(urteil="freigabe", zusammenfassung="Jetzt sauber.")]
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag", lambda *a, **k: urteile.pop(0) if urteile else urteile
    )

    bericht = agent_mit_doppel.run_cycle()

    assert any("nachgebessert (1. Runde)" in s for s in bericht.steps)
    assert not any("bleibt beanstandet" in s for s in bericht.steps)


def test_nach_der_nachbesserung_wird_erneut_geprueft(agent_mit_doppel, monkeypatch):
    """Eine Nachbesserung ohne zweite Pruefung waere nur eine Behauptung."""
    aufrufe = {"n": 0}

    def zaehlend(*a, **k):
        aufrufe["n"] += 1
        return _mit_befund() if aufrufe["n"] == 1 else Pruefbericht(
            urteil="freigabe", zusammenfassung="ok"
        )

    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", zaehlend)
    agent_mit_doppel.run_cycle()

    assert aufrufe["n"] == 2


def test_es_wird_nicht_endlos_nachgebessert(agent_mit_doppel, monkeypatch):
    """Ein Thema, das nicht traegt, traegt auch nach der fuenften Runde nicht."""
    aufrufe = {"n": 0}

    def immer_schlecht(*a, **k):
        aufrufe["n"] += 1
        return _mit_befund()

    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", immer_schlecht)
    bericht = agent_mit_doppel.run_cycle()

    # Eine Erstpruefung plus genau eine Nachbesserung mit ihrer Pruefung.
    assert aufrufe["n"] == 2
    assert any("bleibt beanstandet" in s for s in bericht.steps)


def test_ohne_nachbesserungen_bleibt_alles_wie_vorher(agent_mit_doppel, monkeypatch):
    agent = agent_mit_doppel
    agent.settings.posting.nachbesserungen = 0
    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", lambda *a, **k: _mit_befund())

    bericht = agent.run_cycle()

    assert not any("nachgebessert" in s for s in bericht.steps)


def test_ein_sauberer_beitrag_wird_nicht_nachgebessert(agent_mit_doppel):
    """Sonst kostet jeder Beitrag doppelt, ohne dass sich etwas aendert."""
    bericht = agent_mit_doppel.run_cycle()

    assert not any("nachgebessert" in s for s in bericht.steps)


def test_nachbessern_ersetzt_die_befunde(agent_mit_doppel, monkeypatch):
    """Der alte Prüfbericht gilt für den alten Text - er darf nicht stehenbleiben."""
    agent = agent_mit_doppel
    agent.settings.posting.nachbesserungen = 0
    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", lambda *a, **k: _mit_befund())
    agent.run_cycle()

    entwurf = agent.store.pending_drafts()[0]

    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: Pruefbericht(urteil="freigabe", zusammenfassung="Jetzt sauber."),
    )
    ergebnis = agent.nachbessern(entwurf["id"])

    assert ergebnis["ok"] and ergebnis["urteil"] == "freigabe"
    assert "Jetzt sauber" in agent.store.get_post(entwurf["id"])["pruefung_json"]


# --- Das Motiv bleibt ------------------------------------------------------
#
# Der Fall aus dem Betrieb: Eine Zahl in der Bildunterschrift war falsch.
# Nachbessern hat daraufhin auch das Bild neu gemalt - und dann stand ein
# ganz anderer Fisch über einem Text, der von etwas anderem handelte. Eine
# Faktenkorrektur ist kein Grund, das Motiv zu wechseln. Dafür gibt es
# "Bild neu".


def test_nachbessern_malt_kein_neues_bild(agent_mit_doppel, monkeypatch):
    agent = agent_mit_doppel
    agent.settings.posting.nachbesserungen = 0
    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", lambda *a, **k: _mit_befund())
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]

    gemalt = []
    monkeypatch.setattr(
        agent, "_erzeuge_bild", lambda *a, **k: (gemalt.append(1), (None, None))[1]
    )
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: Pruefbericht(urteil="freigabe", zusammenfassung="Jetzt sauber."),
    )

    agent.nachbessern(entwurf["id"])

    assert gemalt == [], "eine Faktenkorrektur darf kein neues Motiv erzeugen"


def test_bleibt_der_text_auf_dem_bild_gleich_bleibt_das_bild(agent_mit_doppel, monkeypatch):
    agent = agent_mit_doppel
    agent.settings.posting.nachbesserungen = 0
    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", lambda *a, **k: _mit_befund())
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]

    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: Pruefbericht(urteil="freigabe", zusammenfassung="Jetzt sauber."),
    )
    ergebnis = agent.nachbessern(entwurf["id"])

    assert ergebnis["bild"] == "unverändert"
    assert agent.store.get_post(entwurf["id"])["image_path"] == entwurf["image_path"]


def test_eine_falsche_zahl_auf_dem_bild_wird_neu_gesetzt(agent_mit_doppel, monkeypatch, tmp_path):
    """Dasselbe Motiv, andere Schrift - dafür wird das Grundbild aufgehoben."""
    from PIL import Image

    from insta_agent.models import PostDraft

    agent = agent_mit_doppel
    agent.settings.posting.nachbesserungen = 0
    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", lambda *a, **k: _mit_befund())
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]

    # So, als hätte der Bilddienst gemalt: ein Grundbild ohne Schrift.
    roh = tmp_path / "roh.png"
    Image.new("RGB", (1080, 1920), (9, 30, 44)).save(roh)
    agent.store.setze_rohbild(entwurf["id"], str(roh))

    korrigiert = PostDraft.model_validate(_entwurf().model_dump())
    korrigiert.hook_text_on_screen = "8.062 Meter. Und es wartet nicht."
    korrigiert.visual.headline = korrigiert.hook_text_on_screen
    monkeypatch.setattr("insta_agent.runner.ueberarbeite_beitrag", lambda *a, **k: korrigiert)
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: Pruefbericht(urteil="freigabe", zusammenfassung="Jetzt sauber."),
    )

    ergebnis = agent.nachbessern(entwurf["id"])

    assert ergebnis["bild"] == "neu beschriftet"
    neues = Path(agent.store.get_post(entwurf["id"])["image_path"])
    assert neues.is_file() and neues != Path(entwurf["image_path"])
    # Das Grundbild hat den Tausch überlebt - es ist das Motiv.
    assert agent.store.get_post(entwurf["id"])["rohbild_path"] == str(roh)


def test_der_bildprompt_bleibt_wie_er_war(agent_mit_doppel, monkeypatch):
    """Sonst wechselt das Motiv beim nächsten "Bild neu" doch noch."""
    from insta_agent.models import PostDraft

    agent = agent_mit_doppel
    agent.settings.posting.nachbesserungen = 0
    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", lambda *a, **k: _mit_befund())
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]
    alter_prompt = _entwurf().image_generation_prompt

    anders = PostDraft.model_validate(_entwurf().model_dump())
    anders.image_generation_prompt = "a completely different animal, studio light"
    monkeypatch.setattr("insta_agent.runner.ueberarbeite_beitrag", lambda *a, **k: anders)
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: Pruefbericht(urteil="freigabe", zusammenfassung="Jetzt sauber."),
    )

    agent.nachbessern(entwurf["id"])

    import json

    danach = json.loads(agent.store.get_post(entwurf["id"])["draft_json"])
    assert danach["image_generation_prompt"] == alter_prompt


def test_ein_freigegebener_beitrag_wird_nicht_mehr_angefasst(agent_mit_doppel, monkeypatch):
    """Was schon unterwegs ist, darf sich nicht unter der Hand aendern."""
    agent = agent_mit_doppel
    agent.settings.posting.nachbesserungen = 0
    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", lambda *a, **k: _mit_befund())
    agent.run_cycle()

    entwurf = agent.store.pending_drafts()[0]
    agent.store.freigeben(entwurf["id"])

    ergebnis = agent.nachbessern(entwurf["id"])

    assert not ergebnis["ok"]
    assert "Entwurf" in ergebnis["grund"]


# --- Nur das Bild tauschen -------------------------------------------------


def test_ein_neues_bild_laesst_den_text_in_ruhe(agent_mit_doppel):
    """Wem das Bild nicht gefaellt, will nicht den ganzen Beitrag neu."""
    agent = agent_mit_doppel
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]
    alter_text, altes_bild = entwurf["caption"], entwurf["image_path"]

    ergebnis = agent.bild_neu(entwurf["id"])

    assert ergebnis["ok"]
    danach = agent.store.get_post(entwurf["id"])
    assert danach["caption"] == alter_text
    assert danach["image_path"] != altes_bild


def test_der_pruefbericht_bleibt_beim_bildtausch_stehen(agent_mit_doppel):
    """Die Endpruefung sieht Zahlen an, nicht Bilder - sie gilt weiter."""
    agent = agent_mit_doppel
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]
    vorher = entwurf["pruefung_json"]
    assert vorher

    agent.bild_neu(entwurf["id"])

    assert agent.store.get_post(entwurf["id"])["pruefung_json"] == vorher


def test_beim_bildtausch_sieht_die_bildsprache_noch_einmal_hin(agent_mit_doppel, monkeypatch):
    """Ein zweiter Wurf mit demselben Prompt sieht fast gleich aus."""
    agent = agent_mit_doppel
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]

    gesehen = {"n": 0}
    echte = agent_mit_doppel.__class__._gestalte

    def zaehlend(self, *a, **k):
        gesehen["n"] += 1
        return echte(self, *a, **k)

    monkeypatch.setattr(agent.__class__, "_gestalte", zaehlend)
    agent.bild_neu(entwurf["id"])

    assert gesehen["n"] == 1


def test_ein_veroeffentlichter_beitrag_bekommt_kein_neues_bild(agent_mit_doppel):
    """Was draussen ist, aendert sich nicht mehr unter der Hand."""
    agent = agent_mit_doppel
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]
    agent.store.freigeben(entwurf["id"])

    assert not agent.bild_neu(entwurf["id"])["ok"]


def test_bei_alten_entwuerfen_wird_das_grundbild_wiedergefunden(
    agent_mit_doppel, monkeypatch, tmp_path
):
    """Die Spalte kam später dazu - die Datei lag aber immer schon daneben."""
    from PIL import Image

    from insta_agent.models import PostDraft

    agent = agent_mit_doppel
    agent.settings.posting.nachbesserungen = 0
    monkeypatch.setattr("insta_agent.runner.pruefe_beitrag", lambda *a, **k: _mit_befund())
    agent.run_cycle()
    entwurf = agent.store.pending_drafts()[0]

    # So, wie es vor der Änderung aussah: zwei Dateien, keine Spalte.
    roh = agent.settings.media_dir / "alt-roh.png"
    fertig = agent.settings.media_dir / "alt-fertig.png"
    roh.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1920), (9, 30, 44)).save(roh)
    Image.new("RGB", (1080, 1920), (9, 30, 44)).save(fertig)
    agent.store.setze_bild(entwurf["id"], _entwurf(), str(fertig))
    agent.store.setze_rohbild(entwurf["id"], None)

    korrigiert = PostDraft.model_validate(_entwurf().model_dump())
    korrigiert.hook_text_on_screen = "8.062 Meter tief."
    monkeypatch.setattr("insta_agent.runner.ueberarbeite_beitrag", lambda *a, **k: korrigiert)
    monkeypatch.setattr(
        "insta_agent.runner.pruefe_beitrag",
        lambda *a, **k: Pruefbericht(urteil="freigabe", zusammenfassung="Jetzt sauber."),
    )

    assert agent.nachbessern(entwurf["id"])["bild"] == "neu beschriftet"
