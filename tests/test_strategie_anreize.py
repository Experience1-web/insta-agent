"""Ein Wochenziel darf sich nicht gegen die Endprüfung richten.

Im Betrieb aufgetaucht: Der Agent nahm sich "null Verwerfungen - jeder
begonnene Entwurf geht raus" als Kennzahl vor. Der Gedanke dahinter war
richtig - jeder weggeworfene Entwurf ist bezahltes Denken. Die Kennzahl
ist es nicht: Wenn die Endprüfung einen erfundenen Fund findet, muss der
Entwurf sterben. Ein Ziel, das jeden Entwurf hinausgehen sehen will,
belohnt das Durchwinken.

Dazu die zweite Sache aus demselben Plan: sieben Beiträge vorgenommen
bei einer Kasse, die für zwei reicht. Der Plan bricht dann mitten in der
Woche ab - bezahlt ist er trotzdem.
"""

from __future__ import annotations

from insta_agent.brain.strategy import update_strategy
from test_cycle import _analyse, _identitaet, _reflexion, _strategie


class FakeBrain:
    def __init__(self):
        self.aufruf: dict = {}
        self.suchbudget = 4

    def structured(self, **kwargs):
        self.aufruf = kwargs
        return _strategie()


class Kasse:
    seed_usd = 10.0
    earned_usd = 0.0
    spent_usd = 8.03
    balance_usd = 1.97
    cost_coverage = 0.0

    class mode:
        value = "normal"


def _plane(brain):
    return update_strategy(
        brain,
        identity=_identitaet(),
        previous=_strategie(),
        analysis=_analyse(),
        reflection=_reflexion(),
        performance="1 Beitrag, Reichweite 2, 0 Follower",
        treasury_state=Kasse(),
    )


def test_die_verwerfungsquote_ist_ausdruecklich_kein_ziel():
    brain = FakeBrain()

    _plane(brain)

    auftrag = brain.aufruf["prompt"]
    assert "kein Ziel" in auftrag
    assert "Durchwinken" in auftrag


def test_stattdessen_wird_die_zulassungsregel_verlangt():
    """Die Ursache liegt davor: Es wird zu früh angefangen."""
    brain = FakeBrain()

    _plane(brain)

    assert "Zulassungsregel" in brain.aufruf["prompt"]


def test_der_plan_muss_durchgerechnet_werden():
    brain = FakeBrain()

    _plane(brain)

    auftrag = brain.aufruf["prompt"]
    assert "Rechne deinen Plan durch" in auftrag
    # Mit einer Hausnummer, sonst bleibt es eine Floskel.
    assert "dreissig bis fünfzig Cent" in auftrag


def test_gekuerzt_werden_beitraege_nicht_pruefungen():
    brain = FakeBrain()

    _plane(brain)

    assert "nicht die Prüfungen" in brain.aufruf["prompt"]


def test_der_kontostand_liegt_dem_plan_bei():
    """Ohne die Zahl kann er nicht rechnen."""
    brain = FakeBrain()

    _plane(brain)

    assert "1.97" in brain.aufruf["prompt"] or "1,97" in brain.aufruf["prompt"]
