"""Echte Aufnahmen - und nur solche, die man auch nehmen darf.

Ein gemaltes Bild zeigt, wie etwas aussehen könnte. Bei einem Fund ist
das die zweitbeste Lösung: Wer liest, dass 140 Münzen 1.800 Jahre
unberührt lagen, will die Münzen sehen.

Das Problem ist nicht das Finden, sondern das Dürfen. Ein
Urheberrechtsverstoß kostet auf Instagram im Wiederholungsfall das Konto -
also genau das, was dieser Betrieb sonst überall zu vermeiden versucht.
Deshalb ist die Lizenzprüfung hier die eigentliche Prüfung, und sie ist
absichtlich streng: Was nicht ausdrücklich erlaubt ist, wird nicht
genommen.
"""

from __future__ import annotations

import httpx
import pytest

from insta_agent.imaging.echtbild import (
    MINDESTBREITE,
    Fundbild,
    darf_genutzt_werden,
    finde_und_hole,
    suche_bild,
)


def _antwort(*bilder) -> dict:
    """Eine Antwort von Commons mit diesen Bildern."""
    return {
        "query": {
            "pages": {
                str(i): {
                    "title": b.get("titel", f"File:Bild{i}.jpg"),
                    "imageinfo": [
                        {
                            "thumburl": b.get("url", "https://upload.example/bild.jpg"),
                            "thumbwidth": b.get("breite", 1440),
                            "thumbheight": b.get("hoehe", 1080),
                            "extmetadata": {
                                "LicenseShortName": {"value": b["lizenz"]},
                                "Artist": {
                                    "value": b.get("urheber", '<a href="#">Jane Doe</a>')
                                },
                            },
                        }
                    ],
                }
                for i, b in enumerate(bilder)
            }
        }
    }


def _client(daten, *, bilddaten=b"JPEGDATEN"):
    def antworte(anfrage: httpx.Request) -> httpx.Response:
        if "api.php" in anfrage.url.path:
            return httpx.Response(200, json=daten)
        return httpx.Response(200, content=bilddaten)

    return httpx.Client(transport=httpx.MockTransport(antworte))


# --- Die Lizenzgrenze ------------------------------------------------------


@pytest.mark.parametrize(
    "lizenz",
    ["CC0", "Public domain", "PD-old", "CC BY 4.0", "CC BY-SA 3.0", "cc-by-sa-4.0"],
)
def test_freie_lizenzen_sind_erlaubt(lizenz):
    assert darf_genutzt_werden(lizenz)


@pytest.mark.parametrize(
    "lizenz",
    [
        "CC BY-NC 4.0",
        "CC BY-NC-SA 4.0",
        "CC BY-ND 4.0",
        "Fair use",
        "Nonfree",
        "",
        "Alle Rechte vorbehalten",
    ],
)
def test_alles_andere_faellt_durch(lizenz):
    """NC verbietet das Geschäftliche, ND schon das Beschriften."""
    assert not darf_genutzt_werden(lizenz)


def test_nc_sticht_das_enthaltene_by():
    """"CC BY-NC 4.0" enthält "cc by" - ohne die Sperre käme es durch."""
    assert darf_genutzt_werden("CC BY 4.0")
    assert not darf_genutzt_werden("CC BY-NC 4.0")


# --- Die Suche -------------------------------------------------------------


def test_ein_freies_bild_wird_genommen():
    with _client(_antwort({"lizenz": "CC BY-SA 4.0"})) as client:
        bild = suche_bild("Aquincum coins", client=client)

    assert bild is not None
    assert bild.lizenz == "CC BY-SA 4.0"
    # Das Markup aus Commons gehört nicht in die Bildunterschrift.
    assert bild.urheber == "Jane Doe"


def test_ein_unfreies_bild_wird_uebergangen():
    with _client(_antwort({"lizenz": "CC BY-NC 4.0"})) as client:
        assert suche_bild("x", client=client) is None


def test_das_erste_freie_wird_genommen_nicht_das_erste_ueberhaupt():
    daten = _antwort(
        {"lizenz": "Fair use", "titel": "File:Gesperrt.jpg"},
        {"lizenz": "CC0", "titel": "File:Frei.jpg"},
    )
    with _client(daten) as client:
        bild = suche_bild("x", client=client)

    assert bild is not None and bild.seite == "File:Frei.jpg"


def test_zu_kleine_bilder_taugen_nicht():
    """Hochskaliert sieht schlechter aus als gemalt."""
    with _client(_antwort({"lizenz": "CC0", "breite": MINDESTBREITE - 1})) as client:
        assert suche_bild("x", client=client) is None


def test_ohne_treffer_wird_gemalt():
    with _client({"query": {"pages": {}}}) as client:
        assert suche_bild("gibtsnicht", client=client) is None


def test_ein_ausfall_des_archivs_haelt_nichts_auf():
    """Ohne Foto wird gemalt - das ist kein Fehler, nur weniger."""

    def kaputt(anfrage: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Netz weg")

    with httpx.Client(transport=httpx.MockTransport(kaputt)) as client:
        assert suche_bild("x", client=client) is None


# --- Herunterladen ---------------------------------------------------------


def test_das_bild_landet_auf_der_platte(tmp_path):
    ziel = tmp_path / "echt.jpg"
    with _client(_antwort({"lizenz": "CC0"}), bilddaten=b"INHALT") as client:
        bild = finde_und_hole("x", ziel, client=client)

    assert bild is not None
    assert bild.pfad == ziel
    assert ziel.read_bytes() == b"INHALT"


def test_eine_leere_antwort_gilt_nicht_als_bild(tmp_path):
    with _client(_antwort({"lizenz": "CC0"}), bilddaten=b"") as client:
        assert finde_und_hole("x", tmp_path / "leer.jpg", client=client) is None


# --- Die Pflichtangabe -----------------------------------------------------


def test_der_nachweis_nennt_urheber_und_lizenz(tmp_path):
    bild = Fundbild(
        url="https://upload.example/x.jpg",
        pfad=tmp_path / "x.jpg",
        lizenz="CC BY-SA 4.0",
        urheber="Jane Doe",
        seite="File:Muenzen.jpg",
        breite=1440,
        hoehe=1080,
    )

    assert "Jane Doe" in bild.nachweis
    assert "CC BY-SA 4.0" in bild.nachweis
    assert "Wikimedia Commons" in bild.nachweis


def test_ohne_urheber_steht_wenigstens_die_lizenz_da(tmp_path):
    bild = Fundbild("https://u.example/x.jpg", tmp_path / "x.jpg", "CC0", "", "File:X.jpg", 1440, 1080)

    assert "unbekannt" in bild.nachweis
    assert "CC0" in bild.nachweis


def test_der_nachweis_geht_mit_der_bildunterschrift_hinaus():
    """Er ist die Bedingung der Lizenz, keine Zierde."""
    from insta_agent.instagram.publisher import Publisher
    from test_cycle import _entwurf

    caption = Publisher.full_caption(_entwurf(), "Bild: Jane Doe · CC BY-SA 4.0")

    assert "Jane Doe" in caption
    # Vor den Hashtags, nicht dazwischen.
    assert caption.index("Jane Doe") < caption.index("#")


def test_bei_gemaltem_bild_steht_kein_nachweis():
    from insta_agent.instagram.publisher import Publisher
    from test_cycle import _entwurf

    assert "Bild:" not in Publisher.full_caption(_entwurf(), "")


def test_die_adresse_ueberlebt_den_weg_zum_download(tmp_path):
    """Ein Path frisst den doppelten Schrägstrich in https:// - deshalb
    sind Adresse und Datei zwei getrennte Felder."""
    with _client(_antwort({"lizenz": "CC0", "url": "https://upload.example/a/b.jpg"})) as client:
        bild = suche_bild("x", client=client)

    assert bild is not None
    assert bild.url == "https://upload.example/a/b.jpg"
    assert bild.pfad is None


# --- Die echte Aufnahme kommt vor allem anderen ----------------------------


def test_die_echte_aufnahme_kommt_auch_ohne_eingerichteten_bilddienst(
    tmp_path, monkeypatch
):
    """Ein frei verfuegbares Foto ging verloren, wenn kein Maler dastand.

    Die Suche stand hinter der Pruefung auf den Bildgenerator. Wer keinen
    eingerichtet hatte - oder wessen Dienst sich nicht aufbauen liess -
    bekam die typografische Fassung, obwohl eine echte Aufnahme des Fundes
    bereitlag. Genau die ist bei einer Entdeckung das Wertvollste: Wer
    liest, dass etwas gefunden wurde, will es sehen. Und sie kostet
    nichts, braucht keinen Schluessel und kein Kontingent.
    """
    from PIL import Image

    import insta_agent.imaging.echtbild as echtbild_modul
    import insta_agent.runner as runner_modul

    quelle = tmp_path / "echt.jpg"
    Image.new("RGB", (900, 1200), (60, 70, 80)).save(quelle)

    class Gefunden:
        pfad = quelle
        lizenz = "CC BY 4.0"
        seite = "https://commons.wikimedia.org/wiki/File:X.jpg"
        nachweis = "Bild: jemand · CC BY 4.0 · via Wikimedia Commons"

    gesucht: list[str] = []

    def statt_der_suche(suchwort, ziel, **rest):
        gesucht.append(suchwort)
        return Gefunden()

    monkeypatch.setattr(echtbild_modul, "finde_und_hole", statt_der_suche)

    class Laden:
        def __init__(self) -> None:
            self.eintraege: list[tuple[str, str]] = []

        def log(self, art: str, text: str) -> None:
            self.eintraege.append((art, text))

    class BildEinstellung:
        aktiv = False

    class Einstellungen:
        bild = BildEinstellung()
        media_dir = tmp_path

    agent = object.__new__(runner_modul.Agent)
    agent.bildgenerator = None  # genau der Fall, um den es geht
    agent.store = Laden()
    agent.settings = Einstellungen()
    agent._letzter_nachweis = ""

    class Bericht:
        steps: list[str] = []

    class Fund:
        bildsuche = "Bronzemuenzen Hortfund"

    class Spec:
        pass

    class Entwurf:
        bildtext = "1.800 Jahre unberuehrt"
        visual = None
        image_generation_prompt = ""

    class Ich:
        handle = "erstfund"

    bericht = Bericht()
    bericht.steps = []

    fertig, roh = agent._erzeuge_bild(Entwurf(), "test", Ich(), bericht, Fund())

    assert gesucht == ["Bronzemuenzen Hortfund"]
    assert fertig is not None, "Die echte Aufnahme wurde uebergangen"
    assert roh == quelle
    assert agent._letzter_nachweis == Gefunden.nachweis
    assert ("bild_echt", f"{Gefunden.seite} - {Gefunden.lizenz}") in agent.store.eintraege


# --- Openverse: die zweite Quelle ------------------------------------------


def _zwei_quellen(commons: dict, openverse: dict) -> httpx.Client:
    """Ein Netz, in dem beide Archive antworten - jedes mit dem Seinen."""

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        if "openverse" in str(anfrage.url):
            return httpx.Response(200, json=openverse)
        return httpx.Response(200, json=commons)

    return httpx.Client(transport=httpx.MockTransport(antworte))


def _ov(**felder) -> dict:
    grund = {
        "title": "Ausgrabung in Norfolk",
        "license": "by",
        "license_version": "4.0",
        "creator": "Jemand",
        "width": 3000,
        "height": 2000,
        "url": "https://example.test/foto.jpg",
        "foreign_landing_url": "https://example.test/seite",
    }
    grund.update(felder)
    return {"results": [grund]}


def test_openverse_springt_ein_wenn_commons_nichts_hat():
    """Der Grund, warum es ueberhaupt eine zweite Quelle gibt.

    Commons ist gut bei allem, was in einer Enzyklopaedie steht. Es ist
    duenn bei allem, was ein Fotograf aufgenommen hat, ohne dass ein
    Artikel dazu existiert - und das sind oft genau die Bilder, die einen
    Beitrag tragen.
    """
    from insta_agent.imaging.echtbild import suche_bild

    with _zwei_quellen({"query": {"pages": {}}}, _ov()) as client:
        gefunden = suche_bild("Norfolk hoard", client=client)

    assert gefunden is not None
    assert gefunden.url == "https://example.test/foto.jpg"
    assert "CC BY 4.0" in gefunden.lizenz


def test_commons_hat_vorrang_vor_openverse():
    """Dort steht oft genau die Aufnahme, die zur Veroeffentlichung gehoert."""
    from insta_agent.imaging.echtbild import suche_bild

    with _zwei_quellen(_antwort({"lizenz": "CC0"}), _ov()) as client:
        gefunden = suche_bild("x", client=client)

    assert gefunden is not None
    assert "example.test/foto.jpg" not in gefunden.url


def test_openverse_wird_trotz_eigener_filterung_nachgeprueft():
    """Ein Dienst, der sich irrt, darf uns nicht mit hineinziehen.

    Angefragt wird nur, was gewerblich erlaubt ist. Kommt trotzdem etwas
    mit NC zurueck, faellt es hier durch - und nicht erst vor Gericht.
    """
    from insta_agent.imaging.echtbild import suche_bild

    with _zwei_quellen({"query": {"pages": {}}}, _ov(license="by-nc")) as client:
        assert suche_bild("x", client=client) is None

    with _zwei_quellen({"query": {"pages": {}}}, _ov(license="by-nd")) as client:
        assert suche_bild("x", client=client) is None


def test_ein_zu_kleines_openverse_bild_faellt_durch():
    from insta_agent.imaging.echtbild import suche_bild

    with _zwei_quellen({"query": {"pages": {}}}, _ov(width=600, height=400)) as client:
        assert suche_bild("x", client=client) is None


def test_ein_ausfall_von_openverse_haelt_nichts_auf():
    """Zwei Quellen sollen mehr Sicherheit bringen, nicht weniger."""
    from insta_agent.imaging.echtbild import suche_bild

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        if "openverse" in str(anfrage.url):
            raise httpx.ConnectError("Netz weg")
        return httpx.Response(200, json=_antwort({"lizenz": "CC0"}))

    with httpx.Client(transport=httpx.MockTransport(antworte)) as client:
        assert suche_bild("x", client=client) is not None


# --- Bis zum letzten Anlauf ------------------------------------------------


def test_ohne_suchwort_wird_das_themenfeld_genommen():
    """Frueher wurde dann gar nicht gesucht - der teuerste Verzicht.

    Bei einem Account ueber tatsaechlich Geschehenes ist ein gemaltes Bild
    die zweitbeste Loesung. Es gar nicht erst zu versuchen, weil ein Feld
    leer blieb, ist die schlechteste.
    """
    from insta_agent.imaging.echtbild import suchworte_fuer

    class Fund:
        bildsuche = ""
        titel = "Roemischer Muenzhort bei Norfolk"
        gebiet = "Archaeologie"

    worte = suchworte_fuer(Fund())
    assert worte[0] == "Roemischer Muenzhort bei Norfolk"
    assert "archaeological" in worte[-1]


def test_das_ausdrueckliche_suchwort_kommt_zuerst():
    from insta_agent.imaging.echtbild import suchworte_fuer

    class Fund:
        bildsuche = "WASP-121b exoplanet"
        titel = "Eisenregen auf einem fernen Planeten"
        gebiet = "Weltall"

    worte = suchworte_fuer(Fund())
    assert worte[0] == "WASP-121b exoplanet"
    assert len(worte) == 3, "Titel und Themenfeld gehoeren als Rueckfallebene dazu"


def test_ohne_fund_wird_nicht_gesucht():
    from insta_agent.imaging.echtbild import suchworte_fuer

    assert suchworte_fuer(None) == []
