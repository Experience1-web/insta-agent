"""Aus dem Karussell ein Reel - bauen, aktuell halten, veröffentlichen."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

from insta_agent.imaging.reel import REEL, baue_reel, ffmpeg_pfad, ist_aktuell
from insta_agent.instagram.publisher import Publisher
from test_cycle import agent, settings  # noqa: F401 - Fixtures

braucht_ffmpeg = pytest.mark.skipif(ffmpeg_pfad() is None, reason="ffmpeg fehlt")


def _bilder(ordner: Path, n=2) -> list[Path]:
    pfade = []
    for i in range(n):
        pfad = ordner / f"b{i}.png"
        Image.new("RGB", (1080, 1350), (40 + i * 80, 60, 90)).save(pfad)
        pfade.append(pfad)
    return pfade


def _dauer_und_mass(video: Path) -> tuple[float, str]:
    aus = subprocess.run([ffmpeg_pfad(), "-i", str(video)], capture_output=True, text=True).stderr
    dauer = next(z for z in aus.splitlines() if "Duration" in z).split("Duration: ")[1][:11]
    h, m, sek = dauer.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sek), aus


@braucht_ffmpeg
def test_ein_reel_ist_hochkant_hat_ton_und_die_richtige_laenge(tmp_path):
    video = baue_reel(_bilder(tmp_path, 3), tmp_path / "r.mp4", sekunden_je_bild=1.0, fps=10)

    dauer, info = _dauer_und_mass(video)
    assert 2.8 <= dauer <= 3.3
    assert f"{REEL[0]}x{REEL[1]}" in info
    assert "Audio: aac" in info  # stille Tonspur, manche Wege verlangen eine


def test_ohne_bilder_kein_reel(tmp_path):
    from insta_agent.imaging.reel import ReelFehler

    with pytest.raises(ReelFehler):
        baue_reel([tmp_path / "gibtsnicht.png"], tmp_path / "r.mp4")


def test_ein_reel_ist_veraltet_sobald_ein_bild_neuer_ist(tmp_path):
    bilder = _bilder(tmp_path)
    reel = tmp_path / "r.mp4"
    reel.write_bytes(b"x")
    alt = time.time() - 100
    for b in bilder:
        os.utime(b, (alt, alt))
    assert ist_aktuell(reel, bilder)

    os.utime(bilder[1], None)  # Bild eben geändert
    os.utime(reel, (alt, alt))
    assert not ist_aktuell(reel, bilder)
    assert not ist_aktuell(None, bilder)


@braucht_ffmpeg
def test_reel_bauen_und_als_reel_waehlen(agent, tmp_path):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    agent.store.setze_karussell(post_id, [str(p) for p in _bilder(agent.settings.media_dir)])

    assert agent.reel_bauen(post_id)["ok"]
    stand = agent.reel_stand(post_id)
    assert stand["datei"] and stand["aktuell"] and not stand["als_reel"]

    assert agent.veroeffentlichen_als(post_id, True)["ok"]
    assert agent.reel_stand(post_id)["als_reel"]


def test_ohne_karussell_gibt_es_kein_reel(agent):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    agent.store.setze_karussell(post_id, [])
    assert not agent.reel_bauen(post_id)["ok"]


class _ReelClient:
    def __init__(self, reel_klappt=True):
        self.aufrufe = []
        self.reel_klappt = reel_klappt

    def create_reel(self, video_url, caption):
        from insta_agent.instagram.client import GraphAPIError

        self.aufrufe.append(("reel", video_url))
        if not self.reel_klappt:
            raise GraphAPIError("Video abgelehnt")
        return "reel-1"

    def create_container(self, image_url, caption):
        self.aufrufe.append(("bild", image_url))
        return "bild-1"

    def wait_until_ready(self, container_id, **_):
        self.aufrufe.append(("warten", container_id))

    def publish_container(self, container_id):
        return f"media-{container_id}"


def _verlag(tmp_path, client):
    (tmp_path / "media").mkdir(exist_ok=True)
    return Publisher(
        client=client, media_dir=tmp_path / "media", draft_dir=tmp_path / "drafts",
        public_base_url="https://beispiel.de/m", live=True,
    )


def test_ein_gewaehltes_reel_geht_als_reel_hinaus(tmp_path, draft):
    client = _ReelClient()
    verlag = _verlag(tmp_path, client)
    reel = tmp_path / "media" / "r.mp4"
    reel.write_bytes(b"video")
    bild = _bilder(tmp_path / "media")[0]

    ergebnis = verlag.publish(draft, bild, reel=reel)

    assert ergebnis.published and ergebnis.ig_media_id == "media-reel-1"
    assert client.aufrufe[0] == ("reel", "https://beispiel.de/m/r.mp4")


def test_scheitert_das_reel_geht_der_beitrag_als_bild_hinaus(tmp_path, draft):
    client = _ReelClient(reel_klappt=False)
    verlag = _verlag(tmp_path, client)
    reel = tmp_path / "media" / "r.mp4"
    reel.write_bytes(b"video")
    bild = _bilder(tmp_path / "media")[0]

    ergebnis = verlag.publish(draft, bild, reel=reel)

    assert ergebnis.published and ergebnis.ig_media_id == "media-bild-1"
    assert [a[0] for a in client.aufrufe][:2] == ["reel", "bild"]


def test_der_zyklus_baut_das_reel_mit(agent, monkeypatch):
    gebaut = []
    monkeypatch.setattr(agent, "reel_bauen", lambda pid: gebaut.append(pid) or {"ok": True})
    monkeypatch.setattr(
        agent, "_baue_karussell",
        lambda *a, **k: ([Path("/k2.png")], [], None),
    )
    agent.run_cycle()
    assert gebaut, "nach dem Karussell wurde kein Reel gebaut"


def test_json_des_stands_ist_serialisierbar(agent):
    agent.run_cycle()
    post_id = agent.store.pending_drafts()[0]["id"]
    assert json.dumps(agent.reel_stand(post_id))
