"""Die Stoffsuche: kein Beitrag ohne Fund.

Das Problem, das diese Rolle löst, war kein technisches. Der Agent schrieb
sauber, prüfte gewissenhaft und gestaltete ordentlich - und die Beiträge
handelten von der Treppe im Büro und vom Anruf bei der Mutter. Wer
schreibt, nimmt das Thema, das ihm einfällt, und was einem einfällt, ist
der eigene Alltag.

Deshalb wird hier geprüft, was diese Rolle wirklich bewirkt: dass gesucht
wird, bevor geschrieben wird, dass der Fund im Schreibauftrag landet, dass
ein schwacher Fund nicht kommentarlos durchgeht - und dass nichts davon
den Zyklus anhält, wenn die Suche scheitert.
"""

from __future__ import annotations

import json

import pytest

from insta_agent.brain.stoff import SCHWELLE, finde_stoff, fund_block
from insta_agent.models import Fund
# Die Vorrichtungen aus test_cycle mitbenutzen, statt sie abzuschreiben:
# Ein zweiter Agent mit eigener Einrichtung würde irgendwann auseinanderlaufen.
from test_cycle import (  # noqa: F401 - agent und settings sind Fixtures
    FakeBrain,
    _fund,
    _identitaet,
    _strategie,
    agent,
    settings,
)


def _schwach(**felder) -> Fund:
    """Ein Fund, für den niemand anhalten würde."""
    daten = _fund().model_dump()
    daten.update(
        titel="Warum Menschen morgens Kaffee trinken",
        gebiet="Alltag",
        reiz=2,
        verworfen=[],
    )
    daten.update(felder)
    return Fund.model_validate(daten)


class SucheBrain(FakeBrain):
    """Ein Doppel, das der Reihe nach vorgegebene Funde liefert."""

    def __init__(self, config, treasury, api_key=None, funde=None):
        super().__init__(config, treasury, api_key)
        self.funde = list(funde or [])
        self.stoffaufrufe = 0
        self.prompts: dict[str, str] = {}

    def structured(self, *, schema, system, prompt, label, **rest):
        self.prompts[label] = prompt
        if schema is Fund and self.funde:
            self._buchen(label)
            self.stoffaufrufe += 1
            return self.funde.pop(0)
        return super().structured(
            schema=schema, system=system, prompt=prompt, label=label, **rest
        )


def _mit_funden(monkeypatch, *funde):
    """Setzt den Agenten auf eine vorgegebene Folge von Funden."""
    monkeypatch.setattr(
        "insta_agent.runner.Brain",
        lambda config, treasury, api_key=None: SucheBrain(
            config, treasury, api_key, funde=list(funde)
        ),
    )


# --- Der Fund steht am Anfang ---------------------------------------------


def test_der_beitrag_bekommt_den_fund_mit_auf_den_weg(agent):
    agent.run_cycle()

    zeile = agent.store.pending_drafts()[0]
    fund = json.loads(zeile["fund_json"])

    assert fund["titel"] == _fund().titel
    assert fund["gesucht_von"] == "Nell Braake"


def test_gesucht_wird_bevor_geschrieben_wird(agent):
    """Andersherum wäre die Suche sinnlos - das Thema stünde schon fest."""
    agent.run_cycle()

    reihenfolge = agent.brain.aufrufe

    assert reihenfolge.index("Stoff suchen") < reihenfolge.index("Post schreiben")


def test_der_fund_landet_wirklich_im_schreibauftrag(settings, monkeypatch):
    """Sonst wäre er bezahlt und niemand wüsste davon."""
    from insta_agent.runner import Agent

    _mit_funden(monkeypatch, _fund())
    a = Agent(settings)
    try:
        a.run_cycle()
        auftrag = a.brain.prompts["Post schreiben"]
    finally:
        a.close()

    assert _fund().titel in auftrag
    assert _fund().das_detail in auftrag


def test_die_suche_schlaegt_wirklich_nach(agent):
    """Ein Fund aus der Erinnerung ist bei Zahlen und Daten wertlos."""
    agent.run_cycle()

    assert "Stoff suchen" in agent.brain.gesucht


# --- Was passiert, wenn der Fund nichts taugt -----------------------------


def test_ein_schwacher_fund_wird_einmal_nachgesetzt(settings, monkeypatch):
    from insta_agent.runner import Agent

    _mit_funden(monkeypatch, _schwach(), _fund())
    a = Agent(settings)
    try:
        bericht = a.run_cycle()
        aufrufe = a.brain.stoffaufrufe
        gespeichert = json.loads(a.store.pending_drafts()[0]["fund_json"])
    finally:
        a.close()

    assert aufrufe == 2, "genau einmal nachsetzen - jede Runde kostet dasselbe"
    assert gespeichert["titel"] == _fund().titel
    assert any("noch einmal gesucht" in s for s in bericht.steps)


def test_nach_dem_zweiten_versuch_ist_schluss(settings, monkeypatch):
    """Wer zweimal nichts findet, findet auch beim dritten Mal nichts."""
    from insta_agent.runner import Agent

    _mit_funden(monkeypatch, _schwach(), _schwach(titel="Warum Montage schwerfallen"))
    a = Agent(settings)
    try:
        bericht = a.run_cycle()
        aufrufe = a.brain.stoffaufrufe
    finally:
        a.close()

    assert aufrufe == 2
    # Der Beitrag entsteht trotzdem - aber es steht im Protokoll.
    assert any("der Beitrag trägt womöglich nicht" in s for s in bericht.steps)


def test_der_bessere_von_beiden_gewinnt(settings, monkeypatch):
    """Auch der Nachschlag kann schwächer ausfallen als der erste Versuch."""
    from insta_agent.runner import Agent

    erster = _schwach(titel="Ein mittelmäßiger Fund", reiz=3)
    _mit_funden(monkeypatch, erster, _schwach(titel="Ein schlechterer Fund", reiz=1))
    a = Agent(settings)
    try:
        a.run_cycle()
        gespeichert = json.loads(a.store.pending_drafts()[0]["fund_json"])
    finally:
        a.close()

    assert gespeichert["titel"] == "Ein mittelmäßiger Fund"


def test_bei_knapper_kasse_wird_nicht_nachgesetzt(settings, monkeypatch):
    """Im Sparbetrieb ist ein mittelmäßiger Beitrag billiger als zwei Suchen."""
    from insta_agent.economy.ledger import Mode
    from insta_agent.runner import Agent

    _mit_funden(monkeypatch, _schwach(), _fund())
    a = Agent(settings)
    try:
        a.treasury.charge(4.2, "llm")  # unter low_balance
        assert a.treasury.state().mode is Mode.FRUGAL
        a.run_cycle()
        aufrufe = a.brain.stoffaufrufe
    finally:
        a.close()

    assert aufrufe == 1


# --- Nichts davon darf den Zyklus kosten ----------------------------------


def test_eine_gescheiterte_suche_haelt_den_zyklus_nicht_auf(settings, monkeypatch):
    """Ein Beitrag ohne Fund ist schwächer. Kein Beitrag ist schlechter."""
    from insta_agent.runner import Agent

    class KaputteSuche(FakeBrain):
        def structured(self, *, schema, **rest):
            if schema is Fund:
                raise RuntimeError("Suchdienst antwortet nicht")
            return super().structured(schema=schema, **rest)

    monkeypatch.setattr(
        "insta_agent.runner.Brain",
        lambda config, treasury, api_key=None: KaputteSuche(config, treasury, api_key),
    )
    a = Agent(settings)
    try:
        bericht = a.run_cycle()
        entwuerfe = a.store.pending_drafts()
    finally:
        a.close()

    assert bericht.halted_reason is None
    assert len(entwuerfe) == 1
    assert entwuerfe[0]["fund_json"] is None
    assert any("Stoffsuche fehlgeschlagen" in s for s in bericht.steps)


def test_abgeschaltet_wird_nicht_gesucht(settings, monkeypatch):
    from insta_agent.runner import Agent

    settings.posting.stoff_noetig = False
    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    try:
        a.run_cycle()
        aufrufe = a.brain.aufrufe
        entwuerfe = a.store.pending_drafts()
    finally:
        a.close()

    assert "Stoff suchen" not in aufrufe
    assert len(entwuerfe) == 1


def test_abgeschaltet_steht_es_auch_in_der_mannschaft(settings):
    from insta_agent.mannschaft import aufstellung

    settings.posting.stoff_noetig = False

    leute = {m["schluessel"]: m for m in aufstellung(_identitaet(), settings)}

    assert leute["stoff"]["aktiv"] is False


# --- Der Fund bleibt am Beitrag hängen ------------------------------------


def test_dieselbe_ruine_wird_nicht_zweimal_ausgegraben(agent):
    """Die Suche bekommt mit, was schon behandelt wurde."""
    agent.run_cycle()

    assert agent.store.letzte_funde() == [_fund().titel]


def test_der_fund_ueberlebt_das_neuschreiben(store, draft):
    """Beanstandet wird der Text, nicht das, was gefunden wurde.

    Prüfbericht und Gestaltungsurteil gelten nach einer Nachbesserung
    nicht mehr und werden gelöscht. Der Fund schon - sonst wüsste danach
    niemand mehr, worauf der Beitrag überhaupt beruht.
    """
    post_id = store.add_draft(draft, "bild.png")
    store.set_fund(post_id, _fund())

    store.ersetze_entwurf(post_id, draft, "neu.png")

    zeile = store.get_post(post_id)
    assert zeile["pruefung_json"] is None
    assert json.loads(zeile["fund_json"])["titel"] == _fund().titel


def test_die_nachbesserung_bleibt_beim_fund(treasury):
    """Ohne ihn landet der zweite Versuch wieder beim Alltag."""
    from insta_agent.brain.ueberarbeitung import ueberarbeite_beitrag
    from insta_agent.config import LLMConfig
    from insta_agent.models import Befund, Pruefbericht
    from test_cycle import _entwurf

    brain = SucheBrain(LLMConfig(), treasury)
    ueberarbeite_beitrag(
        brain,
        identity=_identitaet(),
        strategy=_strategie(),
        draft=_entwurf(),
        bericht=Pruefbericht(
            urteil="nachbessern",
            zusammenfassung="Die Jahreszahl ist nirgends belegt.",
            befunde=[
                Befund(
                    behauptung="seit 1800 Jahren",
                    urteil="unbelegbar",
                    begruendung="Keine Fundstelle nennt diese Zahl.",
                )
            ],
        ),
        fund=_fund(),
    )

    auftrag = brain.prompts["Beitrag nachbessern"]
    assert _fund().titel in auftrag
    assert "Der Fund bleibt" in auftrag


def test_das_dashboard_zeigt_den_fund(settings, monkeypatch):
    from insta_agent.runner import Agent
    from insta_agent.web import Steuerung

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    a = Agent(settings)
    try:
        a.run_cycle()
    finally:
        a.close()

    entwurf = Steuerung(settings).zustand()["entwuerfe"][0]

    assert entwurf["fund"]["titel"] == _fund().titel
    assert entwurf["fund"]["reiz"] == 5


# --- Die Regeln selbst ----------------------------------------------------


def test_ein_fund_taugt_erst_ab_der_schwelle():
    assert not _schwach().taugt
    assert _fund().taugt
    assert _schwach(reiz=SCHWELLE).taugt


def test_eine_einzelne_quelle_gilt_nicht_als_belegt():
    assert not _schwach(beleglage="unbestaetigt").belegt
    assert _fund().belegt


def test_der_fundblock_nennt_die_beleglage(einstellungen=None):
    """Wer danach arbeitet, muss wissen, wie sicher die Sache ist."""
    text = fund_block(_fund())

    assert "gesichert" in text
    assert _fund().bildidee in text
    assert "Archäologisches Korrespondenzblatt 2026" in text


def test_ohne_fund_bleibt_der_block_leer():
    assert fund_block(None) == ""


def test_der_alltag_ist_ausdruecklich_ausgeschlossen():
    """Ohne diesen Satz kommt die Treppe im Büro zurück."""
    from insta_agent.brain.prompts import PERSONA
    from insta_agent.brain.stoff import STOFF_PERSONA

    for text in (PERSONA, STOFF_PERSONA):
        assert "Alltag" in text
        assert "Gewohnheiten" in text


def test_die_suche_darf_sich_nichts_ausdenken():
    """Gerade bei spektakulären Behauptungen wird nachgeschlagen."""
    from insta_agent.brain.stoff import STOFF_PERSONA

    assert "Du denkst dir nichts aus." in STOFF_PERSONA
    assert "beleglage" in STOFF_PERSONA.lower()


def test_ohne_websuche_wird_das_vermerkt(treasury, store):
    """Sonst sähe ein Fund aus der Erinnerung aus wie ein belegter."""
    from insta_agent.config import LLMConfig

    brain = SucheBrain(LLMConfig(), treasury, funde=[_fund()])
    fund = finde_stoff(
        brain,
        identity=_identitaet(),
        strategy=_strategie(),
        bisherige=[],
        mit_suche=False,
    )

    assert fund.mit_suche is False
    assert "ohne Nachschlagen" in brain.prompts["Stoff suchen"]


def test_schon_behandelte_funde_stehen_im_auftrag(treasury):
    from insta_agent.config import LLMConfig

    brain = SucheBrain(LLMConfig(), treasury, funde=[_fund()])
    finde_stoff(
        brain,
        identity=_identitaet(),
        strategy=_strategie(),
        bisherige=["Ein Wrack in der Ostsee"],
    )

    assert "Ein Wrack in der Ostsee" in brain.prompts["Stoff suchen"]


@pytest.mark.parametrize("gebiet", ["Gewohnheiten", "Produktivität", "Achtsamkeit"])
def test_die_nische_selbst_darf_kein_alltag_sein(gebiet):
    """Die Nische entscheidet über alles Weitere - dort fängt es an."""
    from insta_agent.brain.identity import invent_identity
    from test_cycle import _analyse

    class Mitschrift(FakeBrain):
        auftrag = ""

        def structured(self, *, prompt, **rest):
            Mitschrift.auftrag = prompt
            return super().structured(prompt=prompt, **rest)

    from insta_agent.config import LLMConfig
    from insta_agent.economy.ledger import Treasury
    from insta_agent.store import Store

    store = Store(":memory:")
    try:
        brain = Mitschrift(LLMConfig(), Treasury(store, _sparsam()))
        invent_identity(brain, _analyse())
    finally:
        store.close()

    assert gebiet in Mitschrift.auftrag
    assert "kein Alltag" in Mitschrift.auftrag


def _sparsam():
    from insta_agent.config import EconomyConfig

    return EconomyConfig(treasury_start_usd=10.0)
