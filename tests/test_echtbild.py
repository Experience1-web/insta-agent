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


# Echte JPEG-Bytes, nicht irgendein Wort: Seit eine Fehlerseite nicht
# mehr als Bild durchgeht, muss ein Testbild auch wie eines anfangen.
JPEG = b"\xff\xd8\xff" + b"Bilddaten" * 40


def _client(daten, *, bilddaten=JPEG):
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
    with _client(_antwort({"lizenz": "CC0"}), bilddaten=JPEG) as client:
        bild = finde_und_hole("x", ziel, client=client)

    assert bild is not None
    assert bild.pfad == ziel
    assert ziel.read_bytes() == JPEG


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


# --- Wenn der Anbieter nicht mitspielt -------------------------------------


def test_ein_gesperrtes_original_weicht_auf_openverse_aus(tmp_path):
    """Der Fehler, den der Betreiber beim ersten echten Versuch traf.

    Openverse verweist auf das Original beim Anbieter - Flickr, ein
    Museum, ein Archiv. Die lassen eine fremde Anfrage gern nicht zu,
    und dann stand da "Gefunden, aber nicht ladbar", obwohl Openverse
    dasselbe Bild selbst vorhaelt.
    """
    from insta_agent.imaging.echtbild import hole_bild, suche_bild

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        ziel = str(anfrage.url)
        if "commons.wikimedia" in ziel:
            return httpx.Response(200, json={"query": {"pages": {}}})
        if "anbieter.example" in ziel:
            return httpx.Response(403, text="Forbidden")
        if "thumb" in ziel:
            return httpx.Response(
                200,
                content=b"\xff\xd8\xff" + b"x" * 500,
                headers={"content-type": "image/jpeg"},
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "abc-123",
                        "title": "Seltener Vogel",
                        "license": "by",
                        "license_version": "4.0",
                        "creator": "Ein Fotograf",
                        "width": 3000,
                        "height": 2000,
                        "url": "https://anbieter.example/original.jpg",
                        "thumbnail": "https://api.openverse.org/v1/images/abc-123/thumb/",
                        "foreign_landing_url": "https://anbieter.example/seite",
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(antworte)) as client:
        gefunden = suche_bild("rare bird", client=client)
        assert gefunden is not None
        # Keine doppelten Ausweichadressen - das laedt nur zweimal dasselbe.
        assert len(gefunden.ersatz) == len(set(gefunden.ersatz))

        geladen = hole_bild(gefunden, tmp_path / "vogel.jpg", client=client)

    assert geladen is not None, f"Nicht geladen: {gefunden.grund}"
    assert (tmp_path / "vogel.jpg").exists()


def test_eine_fehlerseite_gilt_nicht_als_bild(tmp_path):
    """200 heisst nicht Bild.

    Wird eine Aufnahme abgelehnt, kommt oft trotzdem ein 200 zurueck -
    nur mit HTML darin. Ohne die Pruefung landet eine Fehlerseite als
    Beitragsbild auf der Platte und faellt erst beim Beschriften auf.
    """
    from insta_agent.imaging.echtbild import Fundbild, hole_bild

    def html(anfrage: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html><body>Nicht gefunden</body></html>" + b" " * 300,
            headers={"content-type": "text/html"},
        )

    bild = Fundbild(
        url="https://anbieter.example/a.jpg",
        pfad=None,
        lizenz="CC0",
        urheber="x",
        seite="y",
        breite=2000,
        hoehe=1500,
    )
    with httpx.Client(transport=httpx.MockTransport(html)) as client:
        assert hole_bild(bild, tmp_path / "a.jpg", client=client) is None

    assert not (tmp_path / "a.jpg").exists()
    assert "text/html" in bild.grund


def test_der_grund_nennt_jede_gescheiterte_adresse(tmp_path):
    """"Nicht ladbar" allein sagt niemandem, woran es lag."""
    from insta_agent.imaging.echtbild import Fundbild, hole_bild

    def abweisend(anfrage: httpx.Request) -> httpx.Response:
        return httpx.Response(403 if "eins" in str(anfrage.url) else 404)

    bild = Fundbild(
        url="https://x.example/eins.jpg",
        pfad=None,
        lizenz="CC0",
        urheber="x",
        seite="y",
        breite=2000,
        hoehe=1500,
        ersatz=["https://x.example/zwei.jpg"],
    )
    with httpx.Client(transport=httpx.MockTransport(abweisend)) as client:
        assert hole_bild(bild, tmp_path / "a.jpg", client=client) is None

    assert "403" in bild.grund and "404" in bild.grund


def test_die_bilanz_unterscheidet_leer_von_wegsortiert():
    """Ein Unterschied wie Tag und Nacht.

    "Nichts gefunden" kann heissen, dass das Archiv nichts hatte - oder
    dass die eigenen Filter alles aussortiert haben. Im einen Fall
    braucht es ein anderes Suchwort, im anderen eine andere Schwelle.
    """
    from insta_agent.imaging.echtbild import Bilanz

    assert str(Bilanz()) == "0 Treffer"
    assert "zu klein" in str(Bilanz(roh=10, zu_klein=10))
    assert "Lizenz" in str(Bilanz(roh=5, lizenz=5))
    assert "Fehler" in str(Bilanz(fehler="ConnectError"))


# --- Wie wir uns vorstellen -------------------------------------------------


def test_jede_anfrage_nennt_eine_kontaktadresse():
    """Der Fehler, an dem die ganze Bildsuche gescheitert ist.

    Wikimedia verlangt eine Kennung, aus der hervorgeht, wer anfragt und
    wo man sich beschweren kann. Wer ohne kommt, bekommt 403 - von der
    Schnittstelle und vom Bildserver gleichermassen. Die Meldung sah
    dann aus, als sei das Bild gesperrt.
    """
    from insta_agent.imaging.echtbild import kennung

    zeile = kennung()
    assert "insta-agent" in zeile
    # Eine Kennung ohne Kontakt ist genau die, die abgewiesen wird.
    assert "http" in zeile
    assert "(" in zeile and ")" in zeile


def test_die_kontaktadresse_laesst_sich_ersetzen(monkeypatch):
    """Wer seine eigene nennen will, soll das koennen.

    Voreingestellt ist die Adresse des Quelltexts, nicht die des
    Betreibers: Eine E-Mail-Adresse gehoert niemandem ungefragt in eine
    Kopfzeile, die an jeden Server geht.
    """
    from insta_agent.imaging.echtbild import HERKUNFT, kennung

    assert HERKUNFT in kennung()
    monkeypatch.setenv("BILD_KONTAKT", "https://meine-seite.example")
    assert "meine-seite.example" in kennung()


def test_die_kennung_geht_wirklich_mit(tmp_path):
    """Eine Kennung, die nur in einer Funktion steht, hilft niemandem."""
    from insta_agent.imaging.echtbild import suche_bild

    gesehen: list[str] = []

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        gesehen.append(anfrage.headers.get("user-agent", ""))
        return httpx.Response(200, json=_antwort({"lizenz": "CC0"}))

    with httpx.Client(transport=httpx.MockTransport(antworte)) as client:
        suche_bild("x", client=client)

    assert gesehen, "Es wurde gar nicht angefragt"
    assert all("insta-agent" in ua and "http" in ua for ua in gesehen), gesehen


def test_der_verweis_geht_nur_an_wikimedia():
    """Ihn an jeden fremden Server zu schicken waere eine Behauptung."""
    from insta_agent.imaging.echtbild import _kopfzeilen

    assert "Referer" in _kopfzeilen("https://upload.wikimedia.org/a.jpg")
    assert "Referer" not in _kopfzeilen("https://live.staticflickr.com/a.jpg")
    # Die Kennung geht ueberallhin - sie ist keine Behauptung, sondern
    # eine Auskunft.
    assert "insta-agent" in _kopfzeilen("https://irgendwo.example/a.jpg")["User-Agent"]


# --- Welches Bild genommen wird --------------------------------------------


def test_das_groesste_ist_nicht_das_beste():
    """Der Fehler, den der erste gelungene Durchlauf gezeigt hat.

    Bei "rare bird" gewann eine Tafel von 2400 x 5317 - kein Foto,
    sondern ein hochkant gescanntes Blatt mit vielen Arten untereinander.
    Sie war schlicht die groesste. Auf Beitragsformat beschnitten saehe
    man davon einen Streifen.
    """
    from insta_agent.imaging.echtbild import guete

    tafel = guete(2400, 5317)
    foto = guete(2400, 3000)
    assert foto > tafel, "Eine Tafel darf kein Foto schlagen"
    # Obwohl die Tafel deutlich mehr Bildpunkte hat.
    assert 2400 * 5317 > 2400 * 3000


def test_ein_panorama_gewinnt_gegen_alles():
    """Daraus wird ein Karussell, durch das man wandert - das schlaegt jedes
    einzelne Bild."""
    from insta_agent.imaging.echtbild import guete

    pano = guete(4800, 1600)
    assert pano > guete(2400, 3000)
    assert pano > guete(3000, 2000)
    assert pano > guete(2400, 2400)


def test_die_groesse_zaehlt_nur_noch_schwach():
    """Ab 2000 Pixel ist ein Bild gut genug fuer Instagram.

    Doppelt so viele Pixel machen es nicht doppelt so brauchbar - sonst
    gewinnt wieder jeder Riesenscan gegen jedes brauchbare Foto.
    """
    from insta_agent.imaging.echtbild import guete

    klein = guete(2000, 2500)
    riesig = guete(8000, 10000)
    # Das Schaerfere gewinnt - sonst entscheidet bei zwei brauchbaren
    # Bildern der Zufall.
    assert riesig > klein
    # Aber nur knapp. Vierfache Kantenlaenge darf die Form nicht schlagen.
    assert riesig / klein < 1.15, "Groesse schlaegt hier wieder die Form"
    assert guete(2400, 3000) > guete(9000, 20000), "Eine Riesentafel gewinnt"


def test_ein_unsinniges_mass_ergibt_keine_guete():
    from insta_agent.imaging.echtbild import guete

    assert guete(0, 100) == 0.0
    assert guete(100, 0) == 0.0


def test_bei_gleichem_format_gewinnt_das_groessere():
    from insta_agent.imaging.echtbild import guete

    assert guete(3000, 3750) > guete(1500, 1875)


def test_die_auswahl_nimmt_wirklich_das_geeignetste():
    """Nicht nur die Funktion - auch der Weg dorthin."""
    from insta_agent.imaging.echtbild import suche_bild

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        if "openverse" in str(anfrage.url):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "1": {
                            "title": "File:Tafel.jpg",
                            "imageinfo": [
                                {
                                    "thumburl": "https://x.example/tafel.jpg",
                                    "thumbwidth": 2400,
                                    "thumbheight": 5317,
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC0"}
                                    },
                                }
                            ],
                        },
                        "2": {
                            "title": "File:Foto.jpg",
                            "imageinfo": [
                                {
                                    "thumburl": "https://x.example/foto.jpg",
                                    "thumbwidth": 2000,
                                    "thumbheight": 2500,
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC0"}
                                    },
                                }
                            ],
                        },
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(antworte)) as client:
        gefunden = suche_bild("rare bird", client=client)

    assert gefunden is not None
    assert "foto" in gefunden.url, "Die Tafel hat gewonnen, obwohl sie unbrauchbar ist"
