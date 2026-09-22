"""Bilder vom Fund selbst - aus der Studie, von der Behoerde.

Die Seiten hier sind nachgebaut. Das echte Netz ist in dieser Umgebung
gesperrt, und darauf kommt es auch nicht an: Was schiefgehen kann, ist
das Erkennen der Quelle, das Lesen der Lizenz, das Finden der Bilder
und die Weitergabe an dieselbe Pruefung, die Archivbilder durchlaufen.
Ob eine bestimmte Zeitschrift ihre Seiten heute so baut, zeigt die
Probe im schwarzen Fenster.
"""

from __future__ import annotations

import io
import random

import httpx
from PIL import Image

from insta_agent.imaging.quellbild import (
    aus_der_quelle,
    bildkandidaten,
    erkenne_quelle,
    lizenz_der_seite,
    pruefe_seite,
    quellseiten,
    urheber_der_seite,
)

STUDIE = "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0000001"


def _foto(breite=2000, hoehe=1500, seed=1) -> bytes:
    """Ein Bild, das die Fotopruefung besteht: Struktur, kein weisser Rand."""
    zufall = random.Random(seed)
    klein = Image.new("RGB", (64, 48))
    klein.putdata(
        [
            tuple(zufall.randint(20, 200) for _ in range(3))
            for _ in range(64 * 48)
        ]
    )
    bild = klein.resize((breite, hoehe), Image.BICUBIC)
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", quality=90)
    return puffer.getvalue()


def _studienseite(lizenz="https://creativecommons.org/licenses/by/4.0/") -> str:
    return f"""<html><head>
<meta property="og:image" content="/figure/image?size=large&amp;id=g001">
<meta name="citation_author" content="Anna Müller">
<meta name="citation_author" content="Ben Rossi">
<meta name="citation_journal_title" content="PLOS ONE">
</head><body>
<a rel="license" href="{lizenz}">Lizenz</a>
<img src="/resource/img/logo-plos.png">
<img srcset="/g002-small.jpg 400w, /g002-large.jpg 1800w" src="/g002-small.jpg">
</body></html>"""


def _netz(seite_html: str, bilder: dict[str, bytes], aufgerufen: list[str] | None = None):
    def antworte(anfrage: httpx.Request) -> httpx.Response:
        ziel = str(anfrage.url)
        if aufgerufen is not None:
            aufgerufen.append(ziel)
        for stueck, inhalt in bilder.items():
            if stueck in ziel:
                return httpx.Response(200, content=inhalt)
        return httpx.Response(200, text=seite_html)

    return httpx.Client(transport=httpx.MockTransport(antworte), follow_redirects=True)


# --- Welche Seiten ueberhaupt infrage kommen -------------------------------


def test_studien_und_behoerden_werden_erkannt():
    assert erkenne_quelle(STUDIE).name == "PLOS"
    assert erkenne_quelle("https://zookeys.pensoft.net/article/12345/").name == "Pensoft"
    assert erkenne_quelle("https://images.nasa.gov/details/x").gemeinfrei


def test_nachrichtenseiten_kommen_nicht_infrage():
    """Dort zeigen sie dieselben Bilder - mit Agenturvermerk, nicht frei."""
    for adresse in (
        "https://www.spiegel.de/wissenschaft/goldschatz",
        "https://www.bbc.com/news/science",
        "https://www.theguardian.com/science/2026",
    ):
        assert erkenne_quelle(adresse) is None


def test_eine_nachgemachte_adresse_ist_keine_behoerde():
    """An der Punktgrenze vergleichen - sonst ist "fakenasa.gov" die NASA."""
    assert erkenne_quelle("https://fakenasa.gov/bild") is None
    assert erkenne_quelle("https://nasa.gov.example.com/bild") is None


# --- Die Lizenz muss auf der Seite stehen ---------------------------------


def test_cc_by_auf_der_seite_wird_gelesen():
    assert lizenz_der_seite(_studienseite()) == "CC BY 4.0"


def test_nicht_kommerziell_wird_nicht_genommen():
    """Der Account soll Geld verdienen - NC schliesst genau das aus."""
    assert lizenz_der_seite(
        _studienseite("https://creativecommons.org/licenses/by-nc/4.0/")
    ) is None


def test_keine_bearbeitung_wird_nicht_genommen():
    """Auf jedes Bild kommt Schrift. Unter ND waere schon das verboten."""
    assert lizenz_der_seite(
        _studienseite("https://creativecommons.org/licenses/by-nd/4.0/")
    ) is None


def test_bei_gemischten_lizenzen_wird_nichts_genommen():
    """Welche fuer welches Bild gilt, laesst sich dann nicht auseinanderhalten."""
    seite = _studienseite() + '<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">'
    assert lizenz_der_seite(seite) is None


def test_ohne_vermerk_wird_nichts_genommen():
    assert lizenz_der_seite("<html>Alle Rechte vorbehalten</html>") is None


def test_esa_und_cc0_werden_gelesen():
    assert (
        lizenz_der_seite('<a href="https://creativecommons.org/licenses/by-sa/3.0/igo/">')
        == "CC BY-SA 3.0 IGO"
    )
    assert (
        lizenz_der_seite('<a href="https://creativecommons.org/publicdomain/zero/1.0/">')
        == "CC0 1.0"
    )


# --- Wer genannt werden muss ----------------------------------------------


def test_die_autoren_der_studie_werden_genannt():
    assert (
        urheber_der_seite(_studienseite(), erkenne_quelle(STUDIE))
        == "Anna Müller et al. (PLOS ONE)"
    )


def test_ohne_autoren_wird_die_quelle_genannt():
    nasa = erkenne_quelle("https://www.nasa.gov/x")
    assert urheber_der_seite("<html></html>", nasa) == "NASA"


# --- Welche Bilder eine Seite hergibt -------------------------------------


def test_das_aufmacherbild_kommt_zuerst_und_beiwerk_faellt_raus():
    kandidaten = bildkandidaten(STUDIE, _studienseite())

    assert kandidaten[0] == "https://journals.plos.org/figure/image?size=large&id=g001"
    assert "https://journals.plos.org/g002-large.jpg" in kandidaten
    assert not any("logo" in k for k in kandidaten)
    # Aus srcset die grosse Fassung, nicht die kleine.
    assert "https://journals.plos.org/g002-small.jpg" not in kandidaten


def test_doppelte_bilder_werden_nur_einmal_geladen():
    seite = '<meta property="og:image" content="/a.jpg"><img src="/a.jpg"><img src="/a.jpg">'
    assert bildkandidaten("https://www.nasa.gov/x", seite) == ["https://www.nasa.gov/a.jpg"]


# --- Der ganze Weg ---------------------------------------------------------


def test_eine_nachrichtenseite_wird_nicht_einmal_aufgerufen():
    """Kein Zugriff, kein Download - schon gar nicht auf ein Agenturbild."""
    aufgerufen: list[str] = []
    with _netz("", {}, aufgerufen) as client:
        befund = pruefe_seite("https://www.spiegel.de/x", client=client)
    assert aufgerufen == []
    assert befund.kandidaten is None
    assert "geschützt" in befund.grund


def test_eine_studie_ohne_freien_vermerk_liefert_nichts(tmp_path):
    seite = _studienseite("https://creativecommons.org/licenses/by-nc/4.0/")
    aufgerufen: list[str] = []
    with _netz(seite, {"g001": _foto()}, aufgerufen) as client:
        gefunden = aus_der_quelle([STUDIE], tmp_path / "z.jpg", client=client)
    assert gefunden is None
    # Nur die Seite, kein einziges Bild.
    assert aufgerufen == [STUDIE]


def test_aus_einer_freien_studie_kommt_ein_bild_mit_pflichtangabe(tmp_path):
    bilder = {"g001": _foto(seed=1), "g002-large": _foto(seed=2)}
    weitere: list = []
    with _netz(_studienseite(), bilder) as client:
        gefunden = aus_der_quelle(
            [STUDIE], tmp_path / "z.jpg", client=client, weitere=weitere
        )

    assert gefunden is not None
    assert gefunden.pfad == tmp_path / "z.jpg"
    assert gefunden.pfad.exists()
    assert (gefunden.breite, gefunden.hoehe) == (2000, 1500)
    assert gefunden.nachweis == "Bild: Anna Müller et al. (PLOS ONE) · CC BY 4.0 · via PLOS"
    # Das zweite Bild derselben Studie fuellt das Karussell.
    assert len(weitere) == 1
    assert weitere[0].pfad.exists()


def test_ein_vorschaubildchen_wird_nicht_genommen(tmp_path):
    """Auf Seiten stehen viele kleine Bilder. Hochgerechnet sind sie Brei."""
    seite = '<a href="https://creativecommons.org/licenses/by/4.0/"><img src="/klein.jpg">'
    with _netz(seite, {"klein": _foto(300, 200)}) as client:
        gefunden = aus_der_quelle([STUDIE], tmp_path / "z.jpg", client=client)
    assert gefunden is None


def test_die_herkunftsseite_geht_beim_laden_mit(tmp_path):
    """Manche Zeitschriften liefern Abbildungen nur mit Herkunft aus.

    Mitgeschickt wird sie, weil wir die Seite tatsaechlich aufgerufen
    haben - bei jedem anderen Bild waere sie eine falsche Behauptung.
    """
    verweise: list[str] = []

    def antworte(anfrage: httpx.Request) -> httpx.Response:
        if "g001" in str(anfrage.url):
            verweise.append(anfrage.headers.get("Referer", ""))
            return httpx.Response(200, content=_foto())
        return httpx.Response(200, text=_studienseite())

    with httpx.Client(transport=httpx.MockTransport(antworte)) as client:
        aus_der_quelle([STUDIE], tmp_path / "z.jpg", client=client)
    assert verweise == [STUDIE]


# --- Woher die Adressen kommen --------------------------------------------


def test_die_quellen_des_fundes_werden_mitgenommen():
    """Die Studie steht oft schon unter den Quellen - ohne eigenes Feld."""

    class Fund:
        bildseite = ""
        echtes_bild = "https://www.bbc.com/news/x"
        quellen = [
            "Müller et al. 2026, PLOS ONE, https://journals.plos.org/plosone/article?id=1.",
            "https://www.spiegel.de/y",
            "NASA: https://science.nasa.gov/mission/z",
        ]

    assert quellseiten(Fund()) == [
        "https://journals.plos.org/plosone/article?id=1",
        "https://science.nasa.gov/mission/z",
    ]


def test_die_ausdrueckliche_bildseite_kommt_zuerst():
    class Fund:
        bildseite = "https://zookeys.pensoft.net/article/9/"
        echtes_bild = ""
        quellen = ["https://journals.plos.org/plosone/article?id=1"]

    assert quellseiten(Fund())[0] == "https://zookeys.pensoft.net/article/9/"


# --- Im Zyklus: die Quelle vor dem Archiv, der Rest ins Karussell ---------


def _agent(tmp_path):
    from insta_agent.runner import Agent

    agent = object.__new__(Agent)

    class Laden:
        def __init__(self):
            self.eintraege = []

        def log(self, art, text):
            self.eintraege.append((art, text))

    class Einstellungen:
        media_dir = tmp_path

        class posting:
            bildformat = "feed"
            bilder_ansehen = False

    agent.store = Laden()
    agent.settings = Einstellungen()
    agent.bildgenerator = None
    agent._bilder_heute_aus = ""
    return agent


class _Bericht:
    def __init__(self):
        self.steps = []


class _Fund:
    titel = "Römischer Münzschatz"
    gebiet = "Archäologie"
    bildsuche = "Roman coin hoard"
    bildseite = STUDIE
    echtes_bild = ""
    quellen: list = []


def test_im_zyklus_kommt_das_bild_aus_der_studie_vor_dem_archiv(tmp_path, monkeypatch):
    import insta_agent.imaging.echtbild as echtbild_modul

    archiv_gefragt = []
    monkeypatch.setattr(
        echtbild_modul,
        "finde_und_hole",
        lambda *a, **k: archiv_gefragt.append(a) or None,
    )
    bilder = {"g001": _foto(seed=1), "g002-large": _foto(seed=2)}
    echtes = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *a, **k: echtes(
            transport=httpx.MockTransport(
                lambda anfrage: httpx.Response(200, content=bilder[
                    next(s for s in bilder if s in str(anfrage.url))
                ])
                if any(s in str(anfrage.url) for s in bilder)
                else httpx.Response(200, text=_studienseite())
            ),
            follow_redirects=True,
        ),
    )

    agent = _agent(tmp_path)
    bericht = _Bericht()
    pfad, nachweis = agent._echtes_bild(_Fund(), "test", bericht)

    assert pfad is not None and pfad.exists()
    assert "via PLOS" in nachweis
    # Das Archiv wurde gar nicht erst gefragt.
    assert archiv_gefragt == []
    assert any("vom Fund selbst" in schritt for schritt in bericht.steps)

    # Die zweite Aufnahme aus der Studie fuellt die naechste Karte - ohne
    # dass nach irgendetwas gesucht wird.
    class Karte:
        bildsuche = "coins"
        bildwunsch = ""

    roh, karten_nachweis = agent._karte_rohbild(Karte(), "test", 2)
    assert roh is not None and roh.exists()
    assert "via PLOS" in karten_nachweis
    assert archiv_gefragt == []


def test_ohne_freie_quelle_geht_es_ins_archiv_wie_bisher(tmp_path, monkeypatch):
    import insta_agent.imaging.echtbild as echtbild_modul

    archiv_gefragt = []
    monkeypatch.setattr(
        echtbild_modul,
        "finde_und_hole",
        lambda suchwort, *a, **k: archiv_gefragt.append(suchwort) or None,
    )

    class Fund(_Fund):
        bildseite = "https://www.spiegel.de/wissen/muenzschatz"

    agent = _agent(tmp_path)
    agent._echtes_bild(Fund(), "test", _Bericht())

    assert archiv_gefragt[0] == "Roman coin hoard"
