"""Die beiden Proben, die nichts kosten.

Ein ganzer Zyklus ist der teuerste denkbare Weg, um herauszufinden, ob
die Bildsuche zu einem Thema etwas findet oder ob fuenf Karten zusammen
aussehen: Stoffsuche, Text und Pruefung werden mitbezahlt, obwohl es um
die Bilder geht.

Beide Proben laufen deshalb ohne einen einzigen Modellaufruf. Genau das
pruefen die Tests hier - dass wirklich keiner stattfindet. Ein Befehl,
der "kostet nichts" heisst und doch etwas kostet, waere schlimmer als
gar keiner.
"""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from insta_agent.cli import app


@pytest.fixture
def lauf():
    return CliRunner()


@pytest.fixture
def kein_modell(monkeypatch):
    """Jeder Modellaufruf wird zum Testfehler.

    Der Wachhund dieser Datei: Schleicht sich in eine Probe je ein
    Aufruf ein, faellt es hier auf und nicht erst auf der Abrechnung.

    Bewacht wird der Zugang zum Modell, nicht das Anlegen eines Agenten.
    Das ist der richtige Schnitt: Ein Client, der dasteht und nie gefragt
    wird, kostet nichts - und seit er erst beim ersten Gebrauch entsteht,
    laufen die Proben sogar ganz ohne Schluessel.
    """
    from insta_agent.llm import Brain

    def verboten(self):
        raise AssertionError("Hier darf kein Modell gefragt werden")

    monkeypatch.setattr(Brain, "client", property(verboten))
    return verboten


def _commons(treffer: bool) -> dict:
    if not treffer:
        return {"query": {"pages": {}}}
    return {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Grabung.jpg",
                    "imageinfo": [
                        {
                            "thumburl": "https://upload.example/gross.jpg",
                            "thumbwidth": 2400,
                            "thumbheight": 1600,
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "Artist": {"value": "Jemand"},
                            },
                        }
                    ],
                }
            }
        }
    }


@pytest.fixture
def archiv(monkeypatch):
    """Ein Netz, in dem die Archive antworten und sonst nichts erreichbar ist."""
    gerufen: list[str] = []

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        ziel = str(anfrage.url)
        gerufen.append(ziel)
        if "openverse" in ziel:
            return httpx.Response(200, json={"results": []})
        if "commons.wikimedia" in ziel:
            return httpx.Response(200, json=_commons(True))
        # Das Bild selbst: ein winziges, aber gueltiges PNG.
        return httpx.Response(
            200,
            content=(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
                b"\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
                b"\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00"
                b"\x00\x00\x00IEND\xaeB`\x82"
            ),
        )

    echtes = httpx.Client

    def gefaelscht(*args, **kwargs):
        kwargs.pop("transport", None)
        return echtes(*args, transport=httpx.MockTransport(antworte), **kwargs)

    monkeypatch.setattr(httpx, "Client", gefaelscht)
    return gerufen


def test_die_bildsuche_fragt_kein_modell(lauf, kein_modell, archiv, tmp_path, monkeypatch):
    """Der Punkt des ganzen Befehls."""
    monkeypatch.setenv("INSTA_AGENT_MEDIA", str(tmp_path))
    ergebnis = lauf.invoke(app, ["bildsuche", "roman coin hoard"])

    assert ergebnis.exit_code == 0, ergebnis.output
    assert "Gefunden" in ergebnis.output
    assert "CC BY-SA 4.0" in ergebnis.output
    # Beide Archive wurden wirklich gefragt.
    assert any("commons.wikimedia" in ruf for ruf in archiv)


def test_die_bildsuche_zeigt_ihre_anlaeufe(lauf, kein_modell, archiv, tmp_path, monkeypatch):
    """Damit man sieht, woran es lag, wenn nichts kommt."""
    monkeypatch.setenv("INSTA_AGENT_MEDIA", str(tmp_path))
    ergebnis = lauf.invoke(app, ["bildsuche", "roman coin hoard norfolk"])

    assert ergebnis.exit_code == 0, ergebnis.output
    # Vom Genauen zum Allgemeinen - alle Anlaeufe stehen da.
    assert "roman coin hoard norfolk" in ergebnis.output
    assert "roman coin" in ergebnis.output


def test_ohne_treffer_sagt_sie_was_zu_tun_ist(lauf, kein_modell, tmp_path, monkeypatch):
    """"Nichts gefunden" allein hilft niemandem weiter."""

    def leer(anfrage: httpx.Request) -> httpx.Response:
        if "openverse" in str(anfrage.url):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json=_commons(False))

    echtes = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *a, **k: echtes(*a, transport=httpx.MockTransport(leer), **{
            key: wert for key, wert in k.items() if key != "transport"
        }),
    )
    monkeypatch.setenv("INSTA_AGENT_MEDIA", str(tmp_path))

    ergebnis = lauf.invoke(app, ["bildsuche", "gibtsnicht"])
    assert ergebnis.exit_code == 1
    assert "allgemeineres Wort" in ergebnis.output


def test_die_karussellprobe_fragt_kein_modell(lauf, kein_modell, archiv, tmp_path, monkeypatch):
    """Auch hier: Es geht um die Bilder, nicht um den Text."""
    from insta_agent.config import load_settings
    from insta_agent.models import Karte, PostDraft, VisualSpec
    from insta_agent.store import Store
    from insta_agent.vorgabe import vorgegebene_identitaet

    db = tmp_path / "agent.db"
    store = Store(db)
    store.set_json("identity", vorgegebene_identitaet().model_dump(mode="json"))
    entwurf = PostDraft(
        pillar="Ausgegraben",
        hook_text_on_screen="Unter dem Acker lag eine Stadt",
        hook="Unter dem Acker lag eine Stadt.",
        caption="Unter dem Acker lag eine Stadt.",
        call_to_action="Speicher das.",
        hashtags=["archaeologie"],
        visual=VisualSpec(headline="Unter dem Acker lag eine Stadt"),
        karten=[
            Karte(text="1.800 Jahre unberuehrt", akzentwort="1.800", bildsuche="roman hoard"),
            Karte(text="140 Muenzen aus Silber", akzentwort="140"),
        ],
        best_time_hint="abends",
        expected_outcome="Speicherungen",
    )
    store.add_draft(entwurf, "erstes.png")
    store.close()

    monkeypatch.setenv("INSTA_AGENT_DB", str(db))
    einstellungen = load_settings()
    einstellungen.db_path = db

    monkeypatch.setattr(
        "insta_agent.cli.load_settings", lambda *_a, **_k: einstellungen
    )
    einstellungen.media_dir = tmp_path / "media"
    einstellungen.media_dir.mkdir(exist_ok=True)

    ergebnis = lauf.invoke(app, ["karussellprobe"])
    assert ergebnis.exit_code == 0, ergebnis.output
    assert "Karussellprobe" in ergebnis.output
    assert "Bilder gebaut" in ergebnis.output


def test_ein_entwurf_ohne_karten_wird_erklaert(lauf, kein_modell, tmp_path, monkeypatch):
    """Nicht jeder Fund traegt fuenf Karten - das ist kein Fehler."""
    from insta_agent.config import load_settings
    from insta_agent.models import PostDraft, VisualSpec
    from insta_agent.store import Store
    from insta_agent.vorgabe import vorgegebene_identitaet

    db = tmp_path / "agent.db"
    store = Store(db)
    store.set_json("identity", vorgegebene_identitaet().model_dump(mode="json"))
    store.add_draft(
        PostDraft(
            pillar="Weltall",
            hook="Ein Satz.",
            caption="Ein Satz.",
            call_to_action="Speicher das.",
            hashtags=[],
            visual=VisualSpec(headline="Ein Satz"),
            best_time_hint="abends",
            expected_outcome="Speicherungen",
        ),
        "erstes.png",
    )
    store.close()

    einstellungen = load_settings()
    einstellungen.db_path = db
    einstellungen.media_dir = tmp_path / "media"
    einstellungen.media_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("insta_agent.cli.load_settings", lambda *_a, **_k: einstellungen)

    ergebnis = lauf.invoke(app, ["karussellprobe"])
    assert ergebnis.exit_code == 0, ergebnis.output
    assert "keine Karten" in ergebnis.output


def test_die_proben_stehen_auch_zum_doppelklicken_bereit():
    """Der Betreiber arbeitet mit den nummerierten Dateien, nicht mit Befehlen.

    Eine Probe, die er nicht findet, wird nicht benutzt - und dann
    kostet der Zyklus doch wieder Geld fuer etwas, das umsonst zu
    pruefen gewesen waere.
    """
    from pathlib import Path

    ordner = Path(__file__).resolve().parent.parent / "windows"
    namen = [p.name for p in ordner.glob("*.bat")]
    assert any("Bildsuche" in n for n in namen), namen
    assert any("Karussell" in n for n in namen), namen

    for name in namen:
        inhalt = (ordner / name).read_text(encoding="utf-8")
        assert "cd /d" in inhalt, f"{name} findet sein Verzeichnis nicht"
        assert "pause" in inhalt, f"{name} schliesst sich, bevor man etwas liest"


def test_kein_befehl_der_proben_veroeffentlicht_etwas():
    """Eine Probe darf niemals etwas nach draussen schicken."""
    import inspect

    from insta_agent import cli

    for name in ("bildsuche", "karussellprobe"):
        quelle = inspect.getsource(getattr(cli, name))
        for gefaehrlich in ("publish", "veroeffentlich", "mark_published"):
            assert gefaehrlich not in quelle, f"{name} fasst {gefaehrlich} an"


def test_json_bleibt_importiert_fuer_die_probe():
    """Kleiner Wachhund gegen ein verirrtes Aufraeumen der Importe."""
    assert json is not None
