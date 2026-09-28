"""Der Sparmodus: ein Beitrag zum kleinsten Preis, der die Kriterien noch hält.

Der Betreiber: "lass uns eine funktion einbauen die sparmodus heist bei
der wir mit maximaler einsparung an geld einen beitrag generieren und
dabei so gut wie möglich versuchen alle kriterien zu erfüllen der modus
soll an und aus schaltbar sein und die geschätzten kosten zeigen." Und:
"der generierte beitrag muss auch als sparversion im dashbord
gekennzeichnet sein".
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from insta_agent.config import BildConfig, EconomyConfig, LLMConfig, PostingConfig, Settings
from insta_agent.economy.sparmodus import (
    DAS_BLEIBT,
    SPAR_MODELL,
    beispielrechnung,
    guenstiger,
    niedriger,
    schaetze,
    so_spart_er,
    spar_config,
)
from insta_agent.models import Karte
from insta_agent.runner import Agent
from test_api_requests import agent_mit_mitschrift  # noqa: F401 - Fixture
from test_bildprobe import _agent as _stoffagent
from test_bildprobe import _Bericht, _Fund, _stoffsuche
from test_cycle import agent, settings  # noqa: F401 - Fixtures


# --------------------------------------------------------------------------
# Die Regeln
# --------------------------------------------------------------------------


def test_aus_opus_wird_sonnet_ein_guenstigeres_modell_bleibt():
    assert guenstiger("claude-opus-5") == SPAR_MODELL
    assert guenstiger("claude-fable-5-1") == SPAR_MODELL
    assert guenstiger("claude-haiku-4-5") == "claude-haiku-4-5"
    assert guenstiger("claude-sonnet-5") == "claude-sonnet-5"
    # Unbekannt heißt: im Zweifel teuer - also ersetzt.
    assert guenstiger("claude-gibts-nicht") == SPAR_MODELL
    assert guenstiger(None) == SPAR_MODELL


def test_weniger_nachdenken_aber_nie_mehr():
    assert niedriger("high") == "medium"
    assert niedriger("max") == "medium"
    assert niedriger("low") == "low"


def test_die_einstellungen_im_sparmodus():
    normal = LLMConfig(model="claude-opus-5", effort="high", max_web_searches=4)
    spar = spar_config(normal)

    assert spar.model == SPAR_MODELL
    assert spar.research_model == SPAR_MODELL
    assert spar.effort == "medium"
    assert spar.research_effort == "medium"
    assert spar.max_web_searches == 2
    # Routine und Ausweichmodell bleiben - und das Original ist unberührt.
    assert spar.cheap_model == normal.cheap_model
    assert spar.fallback_model == normal.fallback_model
    assert normal.model == "claude-opus-5" and normal.max_web_searches == 4


def test_wer_schon_weniger_sucht_sucht_nicht_mehr():
    assert spar_config(LLMConfig(max_web_searches=1)).max_web_searches == 1


# --------------------------------------------------------------------------
# Die Schätzung
# --------------------------------------------------------------------------


def _einstellungen(**posting) -> Settings:
    return Settings(llm=LLMConfig(), posting=PostingConfig(**posting))


def test_der_sparmodus_kostet_deutlich_weniger():
    s = _einstellungen()
    normal = beispielrechnung(s, spar=False)
    spar = beispielrechnung(s, spar=True)

    assert 0 < spar < normal
    # Sonnet statt Opus, halb so viele Suchen, keine Nebenarbeiten: mehr
    # als die Hälfte muss dabei herauskommen.
    assert spar < normal * 0.5


def test_ohne_eigene_zyklen_ist_es_eine_beispielrechnung():
    schaetzung = schaetze(_einstellungen(), {}, [])

    assert schaetzung.normal_grundlage == "Beispielrechnung"
    assert schaetzung.spar_grundlage == "Beispielrechnung"
    assert 0.5 < schaetzung.ersparnis < 1


def test_eigene_zyklen_schlagen_die_beispielrechnung():
    zyklen = [
        {"kosten": 0.80, "beitraege": 1, "spar": False},
        {"kosten": 0.60, "beitraege": 1, "spar": False},
        # Abgebrochen, ohne Beitrag - zählt nicht als Beitrag.
        {"kosten": 0.30, "beitraege": 0, "spar": False},
    ]
    schaetzung = schaetze(_einstellungen(), {}, zyklen)

    assert schaetzung.normal_usd == pytest.approx(0.70)
    assert schaetzung.normal_grundlage == "Schnitt deiner letzten 2 Zyklen"
    # Noch kein Sparbeitrag: dasselbe Verhältnis wie in der Rechnung,
    # aber auf die eigene Zahl gelegt.
    s = _einstellungen()
    verhaeltnis = beispielrechnung(s, spar=True) / beispielrechnung(s, spar=False)
    assert schaetzung.spar_usd == pytest.approx(0.70 * verhaeltnis, rel=1e-3)
    assert schaetzung.spar_grundlage == "geschätzt aus deinen Zyklen"


def test_nach_dem_ersten_sparbeitrag_zaehlt_seine_echte_zahl():
    zyklen = [
        {"kosten": 0.27, "beitraege": 1, "spar": True},
        {"kosten": 0.80, "beitraege": 1, "spar": False},
        {"kosten": 0.60, "beitraege": 1, "spar": False},
    ]
    schaetzung = schaetze(_einstellungen(), {}, zyklen)

    assert schaetzung.spar_usd == pytest.approx(0.27)
    assert schaetzung.spar_grundlage == "dein Sparbeitrag"
    assert schaetzung.ersparnis == pytest.approx(1 - 0.27 / 0.70)


def test_eine_echte_sparzahl_wird_nie_gegen_eine_beispielrechnung_gestellt():
    """Sonst stünde da "94 % weniger" - eine Ersparnis, die es nicht gibt."""
    s = _einstellungen()
    schaetzung = schaetze(s, {}, [{"kosten": 0.30, "beitraege": 1, "spar": True}])

    assert schaetzung.spar_usd == pytest.approx(0.30)
    assert schaetzung.normal_grundlage == "hochgerechnet aus deinen Sparbeiträgen"
    verhaeltnis = beispielrechnung(s, spar=True) / beispielrechnung(s, spar=False)
    assert schaetzung.ersparnis == pytest.approx(1 - verhaeltnis, rel=1e-3)


def test_ein_einzelner_normaler_zyklus_ist_noch_kein_schnitt():
    """Der erste Zyklus bringt alles mit, was nur einmal anfällt."""
    schaetzung = schaetze(
        _einstellungen(), {}, [{"kosten": 2.40, "beitraege": 1, "spar": False}]
    )
    assert schaetzung.normal_grundlage == "Beispielrechnung"


def test_abgeschaltete_schritte_kosten_nichts():
    mit = beispielrechnung(_einstellungen(), spar=False)
    ohne = beispielrechnung(_einstellungen(pruefung_noetig=False), spar=False)
    assert ohne < mit


def test_bezahlte_bilder_fallen_im_sparmodus_weg():
    s = _einstellungen()
    s.bild = BildConfig(anbieter="replicate", token="r8_test", kosten_pro_bild_usd=0.04)
    ohne_bild = _einstellungen()

    assert beispielrechnung(s, spar=False) > beispielrechnung(ohne_bild, spar=False)
    assert beispielrechnung(s, spar=True) == pytest.approx(beispielrechnung(ohne_bild, spar=True))
    assert any("bezahlten" in z for z in so_spart_er(s))


def test_die_erklaerung_nennt_was_sich_aendert_und_was_bleibt():
    zeilen = so_spart_er(_einstellungen())
    text = " ".join(zeilen)
    # Nur der Chef steht auf Opus - Suchen und Prüfen laufen schon auf Sonnet.
    assert zeilen[0].startswith("Schreiben mit Sonnet 5 statt Opus 5")
    assert "Suchen" not in zeilen[0]
    assert "2 statt 4 Websuchen" in text
    assert "Marktrecherche" in text
    assert any("Endprüfung" in z for z in DAS_BLEIBT)


def test_stehen_mehrere_rollen_auf_opus_werden_alle_genannt():
    zeilen = so_spart_er(
        _einstellungen(), {"stoff": "claude-opus-5", "pruefung": "claude-opus-5"}
    )
    assert zeilen[0].startswith("Schreiben, Suchen und Prüfen mit Sonnet 5 statt Opus 5")


def test_wer_schon_guenstig_arbeitet_bekommt_kein_falsches_versprechen():
    s = _einstellungen()
    s.llm.model = "claude-sonnet-5"
    assert "bleiben" in so_spart_er(s)[0]


# --------------------------------------------------------------------------
# Der Schalter am Agenten
# --------------------------------------------------------------------------


def test_der_schalter_bleibt_gespeichert(settings, monkeypatch):
    from test_cycle import FakeBrain

    monkeypatch.setattr("insta_agent.runner.Brain", FakeBrain)
    erster = Agent(settings)
    assert erster.sparmodus is False
    erster.setze_sparmodus(True)
    erster.close()

    zweiter = Agent(settings)
    try:
        assert zweiter.sparmodus is True
        assert zweiter.brain.config.model == SPAR_MODELL
        assert zweiter.brain.config.max_web_searches == 2
        arten = [z["message"] for z in zweiter.store.recent_journal(5)]
        assert "Sparmodus eingeschaltet" in arten
        zweiter.setze_sparmodus(False)
        assert zweiter.brain.config is settings.llm
    finally:
        zweiter.close()


def test_im_sparmodus_ist_keine_rolle_teurer_als_sonnet(agent):
    from insta_agent.mannschaft import KEY_MODELLWAHL

    agent.store.set_json(KEY_MODELLWAHL, {"pruefung": "claude-haiku-4-5"})
    assert agent._modell("chef") is None  # Normalbetrieb: Voreinstellung

    agent.setze_sparmodus(True)
    assert agent._modell("chef") == SPAR_MODELL
    assert agent._modell("stoff") == SPAR_MODELL
    # Selbst gewählt und schon günstiger: bleibt.
    assert agent._modell("pruefung") == "claude-haiku-4-5"


def test_ein_sparzyklus_laesst_die_nebenarbeit_weg_und_markiert_den_beitrag(agent):
    agent.setze_sparmodus(True)
    bericht = agent.run_cycle()

    assert bericht.halted_reason is None, bericht.halted_reason
    assert bericht.sparmodus is True
    assert any(s.startswith("Sparmodus:") for s in bericht.steps)

    aufrufe = agent.brain.aufrufe
    for weg in ("Vorbilder ansehen", "Marktrecherche", "Bildsprache", "Geschäftsmodell",
                "Reflexion", "Lohnt sich das noch"):
        assert weg not in aufrufe, weg
    # Was den Beitrag trägt, bleibt: Fund, Text, Endprüfung.
    for bleibt in ("Stoff suchen", "Post schreiben", "Endprüfung"):
        assert bleibt in aufrufe, bleibt
    # Ohne Kurs geht es nicht - der erste wird auch im Sparmodus bestimmt.
    assert "Strategie festlegen" in aufrufe

    # Geschrieben wird mit Sonnet, auch wenn der Chef auf Opus steht.
    assert agent.brain.modelle["Post schreiben"] == SPAR_MODELL
    assert agent.brain.modelle["Stoff suchen"] == SPAR_MODELL

    zeile = agent.store.pending_drafts()[0]
    assert zeile["sparmodus"] == 1
    assert agent.store.zyklen()[0]["spar"] is True
    assert "(Sparmodus)" in agent.store.recent_journal(1)[0]["message"]


def test_ein_bestehender_kurs_wird_im_sparmodus_nicht_neu_hergeleitet(agent):
    from insta_agent.runner import KEY_STRATEGIE_ZYKLUS

    agent.run_cycle()
    # Eine Woche später wäre der Kurs fällig.
    agent.store.set_json(KEY_STRATEGIE_ZYKLUS, -10)
    agent.setze_sparmodus(True)
    vorher = agent.brain.aufrufe.count("Strategie festlegen")
    agent.run_cycle()
    assert agent.brain.aufrufe.count("Strategie festlegen") == vorher


def test_ein_normaler_beitrag_ist_keine_sparversion(agent):
    bericht = agent.run_cycle()
    assert bericht.sparmodus is False
    assert not agent.store.pending_drafts()[0]["sparmodus"]
    assert agent.store.zyklen()[0]["spar"] is False


def test_ohne_foto_wird_im_sparmodus_nicht_nachgesetzt(tmp_path, monkeypatch):
    koralle = _Fund("Koralle")
    gefragt = _stoffsuche(monkeypatch, koralle, _Fund("Goldschatz"))
    agent = _stoffagent(tmp_path, gefunden={"Koralle": (None, None)})
    agent._spar = True
    bericht = _Bericht()

    assert agent._suche_stoff(bericht) is koralle
    assert len(gefragt) == 1
    assert any("im Sparmodus wird nicht nachgesetzt" in s for s in bericht.steps)


def test_ein_zu_schwacher_fund_wird_auch_im_sparmodus_ersetzt(tmp_path, monkeypatch):
    """Ein schwacher Fund trägt keinen Beitrag - das ist ein Kriterium, kein Luxus."""
    from insta_agent.runner import BILD_VOM_FUND

    schwach = _Fund("Wurm", reiz=2)
    stark = _Fund("Goldschatz")
    gefragt = _stoffsuche(monkeypatch, schwach, stark)
    agent = _stoffagent(
        tmp_path,
        gefunden={"Wurm": (None, None), "Goldschatz": (tmp_path / "g.jpg", BILD_VOM_FUND)},
    )
    agent._spar = True

    assert agent._suche_stoff(_Bericht()) is stark
    assert len(gefragt) == 2


class _Maler:
    def __init__(self):
        self.auftraege = []

    def erzeuge(self, prompt, ziel):
        self.auftraege.append(prompt)
        from PIL import Image

        Image.new("RGB", (64, 80), (10, 20, 30)).save(ziel)


class _Kasse:
    def __init__(self):
        self.buchungen = []

    def charge(self, betrag, category, note="", meta=None):
        self.buchungen.append((betrag, category))


def _malagent(tmp_path, preis: float, spar: bool):
    agent = object.__new__(Agent)
    agent.settings = SimpleNamespace(
        media_dir=tmp_path,
        bild=SimpleNamespace(kosten_pro_bild_usd=preis, modell="flux", anbieter="replicate"),
    )
    agent.bildgenerator = _Maler()
    agent.treasury = _Kasse()
    agent._bilder_heute_aus = None
    agent._quellbilder = []
    agent._spar = spar
    return agent


def test_im_sparmodus_wird_nicht_bezahlt_gemalt(tmp_path):
    agent = _malagent(tmp_path, 0.04, spar=True)
    roh, _ = agent._karte_rohbild(Karte(text="Gold", bildwunsch="gold coins"), "b", 2)

    assert roh is None
    assert agent.bildgenerator.auftraege == []


def test_kostenlos_gemalt_wird_auch_im_sparmodus(tmp_path):
    agent = _malagent(tmp_path, 0.0, spar=True)
    roh, _ = agent._karte_rohbild(Karte(text="Gold", bildwunsch="gold coins"), "b", 2)

    assert roh is not None and roh.exists()
    assert agent.treasury.buchungen == []


def test_eine_gemalte_karte_wird_gebucht(tmp_path):
    """Bisher wurde nur das erste Bild eines Beitrags bezahlt verbucht."""
    agent = _malagent(tmp_path, 0.04, spar=False)
    agent._karte_rohbild(Karte(text="Gold", bildwunsch="gold coins"), "b", 2)

    assert agent.treasury.buchungen == [(0.04, "image")]


# --------------------------------------------------------------------------
# Was wirklich an die Schnittstelle geht
# --------------------------------------------------------------------------


def test_im_sparmodus_geht_keine_anfrage_an_opus(agent_mit_mitschrift):
    agent, client = agent_mit_mitschrift
    agent.setze_sparmodus(True)
    bericht = agent.run_cycle()

    assert bericht.halted_reason is None, bericht.halted_reason
    assert client.anfragen
    for anfrage in client.anfragen:
        assert not anfrage["model"].startswith("claude-opus"), anfrage["model"]
        if "output_config" in anfrage:
            assert anfrage["output_config"]["effort"] in ("low", "medium")

    mit_suche = [a for a in client.anfragen if a.get("tools")]
    # Stoffsuche und Endprüfung - die Vorbilder ruhen.
    assert len(mit_suche) == 2
    for anfrage in mit_suche:
        assert anfrage["tools"][0]["max_uses"] == 2
        # Und der Auftrag sagt dem Modell dieselbe Zahl.
        auftrag = anfrage["messages"][0]["content"][0]["text"]
        assert "bis zu 2 Websuchen" in auftrag


def test_ein_sparzyklus_kostet_weniger_als_ein_normaler(agent_mit_mitschrift):
    agent, _ = agent_mit_mitschrift
    agent.run_cycle()  # der erste bringt den Kurs und die Vorbilder mit
    normal = agent.run_cycle().cost_usd
    agent.setze_sparmodus(True)
    spar = agent.run_cycle().cost_usd

    assert 0 < spar < normal


def test_die_websuche_wird_mitbezahlt():
    from insta_agent.economy.pricing import cost_of_usage

    usage = SimpleNamespace(
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        server_tool_use=SimpleNamespace(web_search_requests=3),
    )
    assert cost_of_usage("claude-sonnet-5", usage) == pytest.approx(0.03)


# --------------------------------------------------------------------------
# Das Dashboard
# --------------------------------------------------------------------------


@pytest.fixture
def web_einstellungen(tmp_path):
    s = Settings(
        llm=LLMConfig(),
        economy=EconomyConfig(treasury_start_usd=5.0),
        posting=PostingConfig(),
        db_path=tmp_path / "agent.db",
        media_dir=tmp_path / "media",
        draft_dir=tmp_path / "drafts",
    )
    s.anthropic_api_key = "sk-ant-test"
    return s


def _server(steuerung):
    from insta_agent.web import _handler_klasse

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_klasse(steuerung, None))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _post(server, pfad, rumpf):
    anfrage = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}{pfad}",
        data=json.dumps(rumpf).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=5) as antwort:
            return antwort.status, json.loads(antwort.read())
    except urllib.error.HTTPError as fehler:
        return fehler.code, json.loads(fehler.read())


def test_das_dashboard_zeigt_schalter_und_geschaetzte_kosten(web_einstellungen):
    from insta_agent.web import Steuerung

    spar = Steuerung(web_einstellungen).zustand()["sparmodus"]

    assert spar["an"] is False
    assert 0 < spar["spar_usd"] < spar["normal_usd"]
    assert spar["ersparnis"] > 0.5
    assert spar["so_spart_er"] and spar["das_bleibt"]
    assert spar["normal_grundlage"] == "Beispielrechnung"


def test_der_schalter_laesst_sich_im_dashboard_umlegen(web_einstellungen):
    from insta_agent.web import Steuerung

    steuerung = Steuerung(web_einstellungen)
    server = _server(steuerung)
    try:
        status, antwort = _post(server, "/api/sparmodus", {"an": True})
        assert status == 200 and antwort["ok"] is True
        assert steuerung.zustand()["sparmodus"]["an"] is True

        status, antwort = _post(server, "/api/sparmodus", {"an": "ja"})
        assert status == 400 and antwort["ok"] is False

        status, _ = _post(server, "/api/sparmodus", {"an": False})
        assert status == 200
        assert steuerung.zustand()["sparmodus"]["an"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_im_lesemodus_bleibt_der_schalter_wie_er_ist(web_einstellungen):
    from insta_agent.web import Steuerung

    steuerung = Steuerung(web_einstellungen)
    steuerung.nur_lesen = True
    server = _server(steuerung)
    try:
        status, antwort = _post(server, "/api/sparmodus", {"an": True})
        assert status == 409 and antwort["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
    assert steuerung.zustand()["sparmodus"]["an"] is False


def test_ein_sparbeitrag_ist_im_dashboard_gekennzeichnet(web_einstellungen):
    from insta_agent.web import Steuerung
    from test_cycle import _entwurf

    agent = Agent(web_einstellungen)
    try:
        spar_id = agent.store.add_draft(_entwurf(), None)
        agent.store.setze_sparversion(spar_id)
        normal_id = agent.store.add_draft(_entwurf(), None)
    finally:
        agent.close()

    entwuerfe = {e["id"]: e for e in Steuerung(web_einstellungen).zustand()["entwuerfe"]}
    assert entwuerfe[spar_id]["sparversion"] is True
    assert entwuerfe[normal_id]["sparversion"] is False


def test_die_mannschaft_zeigt_ihr_sparmodell(web_einstellungen):
    from insta_agent.web import Steuerung

    agent = Agent(web_einstellungen)
    try:
        agent.bootstrap()
    finally:
        agent.close()
    leute = {m["schluessel"]: m for m in Steuerung(web_einstellungen).zustand()["mannschaft"]}
    assert leute["chef"]["modell"] == "claude-opus-5"
    assert leute["chef"]["spar_modell"] == SPAR_MODELL
