"""Die Grenze, das Fortsetzen und was ein Beitrag gekostet hat.

Drei Dinge, die zusammengehoeren: Eine Grenze, die man nicht verstellen
kann, stoppt irgendwann mitten im Lauf. Ein Lauf, der gestoppt wurde,
muss sich fortsetzen lassen, ohne die bezahlte Vorarbeit zu wiederholen.
Und wer entscheiden soll, ob ein Beitrag sein Geld wert war, muss wissen,
was er gekostet hat - nicht, was der ganze Zyklus gekostet hat.
"""

from __future__ import annotations

import pytest

from insta_agent.store import Store


def test_die_grenze_laesst_sich_ueber_die_umgebung_setzen(monkeypatch):
    """Sonst muesste man eine Zahl im Quelltext aendern.

    Wie hoch die Grenze gehoert, haengt davon ab, wie viele Rollen auf
    teuren Modellen laufen und wie viele Beitraege ein Zyklus macht. Das
    weiss nur der Betreiber, und er soll es sagen koennen.
    """
    from insta_agent.config import load_settings

    monkeypatch.setenv("ZYKLUS_GRENZE", "4.25")
    assert load_settings().economy.max_cost_per_cycle_usd == pytest.approx(4.25)


def test_eine_unsinnige_grenze_wird_nicht_uebernommen(monkeypatch):
    """Ein Vertipper darf die Bremse nicht ausbauen."""
    from insta_agent.config import load_settings

    monkeypatch.setenv("ZYKLUS_GRENZE", "keine Zahl")
    assert load_settings().economy.max_cost_per_cycle_usd == pytest.approx(1.50)

    # Null hiesse: kein Zyklus kommt je durch.
    monkeypatch.setenv("ZYKLUS_GRENZE", "0")
    assert load_settings().economy.max_cost_per_cycle_usd >= 0.10


def test_die_kosten_eines_beitrags_werden_aufaddiert(tmp_path):
    """Nachbessern kostet erneut - und zaehlt zu demselben Beitrag.

    Wer spaeter fragt, was ein Beitrag gekostet hat, meint alles: den
    ersten Anlauf, die Korrektur und das neu gemalte Bild. Einzeln
    gespeichert waere jede Zahl fuer sich richtig und die Antwort
    trotzdem falsch.
    """
    store = Store(tmp_path / "s.db")
    try:

        class Entwurf:
            pillar = "Weltall"
            caption = "Text"
            hashtags = ["#a"]

            def model_dump(self, mode=None):
                return {"caption": "Text", "hashtags": ["#a"]}

        post_id = store.add_draft(Entwurf(), "bild.png")
        assert store.get_post(post_id)["kosten_usd"] is None

        store.setze_kosten(post_id, 0.4231)
        store.setze_kosten(post_id, 0.1102)

        assert store.get_post(post_id)["kosten_usd"] == pytest.approx(0.5333)
    finally:
        store.close()


def test_ein_alter_beitrag_behaelt_seine_luecke(tmp_path):
    """Keine erfundene Null.

    Beitraege von vor dieser Zaehlung haben keine Kosten hinterlegt. Eine
    Null hinzuschreiben hiesse zu behaupten, sie seien umsonst gewesen -
    "noch nicht mitgerechnet" ist die ehrliche Anzeige.
    """
    store = Store(tmp_path / "s.db")
    try:

        class Entwurf:
            pillar = "Weltall"
            caption = "Text"
            hashtags: list[str] = []

            def model_dump(self, mode=None):
                return {"caption": "Text", "hashtags": []}

        post_id = store.add_draft(Entwurf(), None)
        assert store.get_post(post_id)["kosten_usd"] is None
    finally:
        store.close()


def test_fortsetzen_wiederholt_die_bezahlte_vorarbeit_nicht():
    """Der eigentliche Sinn des Knopfes.

    Greift die Grenze, sind Reflexion, Marktrecherche und Kurs schon
    gedacht und bezahlt - sie stehen im Speicher. Sie noch einmal zu
    denken, waere das Geld ein zweites Mal aus dem Fenster und ein
    anderes Ergebnis obendrein.
    """
    import inspect

    from insta_agent.runner import Agent

    quelle = inspect.getsource(Agent._beende_zyklus_inner)
    for teuer in ("reflect(", "run_market_research(", "update_strategy(", "_pruefe_kurs"):
        assert teuer not in quelle, f"{teuer} gehoert nicht in die Fortsetzung"
    # Was fehlt, wird nachgeholt.
    assert "_produce_posts" in quelle
    assert "_veroeffentliche_freigegebenes" in quelle


def test_ohne_kurs_gibt_es_nichts_fortzusetzen(tmp_path):
    """Dann hat der Zyklus so frueh abgebrochen, dass nichts dasteht.

    Wichtig, dass hier wirklich eine leere Ablage steht: Mit der echten
    laeuft der Test durch, weil dort ein Kurs liegt - und pruefte dann
    gar nichts.
    """
    from datetime import datetime, timezone

    from insta_agent.config import load_settings
    from insta_agent.models import CycleReport
    from insta_agent.runner import Agent

    settings = load_settings()
    settings.db_path = tmp_path / "leer.db"
    settings.media_dir = tmp_path / "media"
    settings.draft_dir = tmp_path / "drafts"

    agent = Agent(settings)
    try:
        assert agent.identity is None and agent.strategy is None

        bericht = CycleReport(started_at=datetime.now(timezone.utc))
        agent._beende_zyklus_inner(1, bericht)

        assert bericht.halted_reason
        assert "normalen Zyklus" in bericht.halted_reason
        # Und vor allem: Es wurde nichts angefangen und nichts bezahlt.
        assert not bericht.drafts_written
    finally:
        agent.close()
