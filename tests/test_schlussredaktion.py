"""Schlussredaktion und Pflichtstellen beim Nachbessern."""

from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from insta_agent.brain.schlussredaktion import Aenderung, Schlussbericht, kontaktbogen
from insta_agent.brain.ueberarbeitung import _pflichtstellen
from insta_agent.models import Befund, Karte, PostDraft, Pruefbericht, VisualSpec


def _entwurf(**felder) -> PostDraft:
    daten = dict(
        pillar="Ausgegraben",
        hook_text_on_screen="Eine Steinplatte",
        image_generation_prompt="",
        hook="",
        caption="Ein Satz.\n\nDer doppelte Satz.\n\n📚 Quelle: Archaeology, 2026",
        body_text="",
        call_to_action="",
        hashtags=[],
        first_comment_prompt="",
        visual=VisualSpec(headline="Eine Steinplatte"),
        best_time_hint="",
        expected_outcome="",
        karten=[Karte(text="Die Platte lag versteckt in einer engen Felsnische"),
                Karte(text="So alt ist die Bemalung")],
    )
    daten.update(felder)
    return PostDraft.model_construct(**daten)


def test_eine_beanstandete_karte_wird_beim_namen_genannt():
    """Sonst ändert das Modell die falschen Karten - so geschehen bei der Steinplatte."""
    bericht = Pruefbericht.model_construct(
        urteil="nachbessern", zusammenfassung="", korrekturen=[], mit_suche=True,
        befunde=[Befund(behauptung="Die Platte lag versteckt in einer engen Felsnische",
                        urteil="unbelegbar", begruendung="Steht nirgends.", beleg="")],
    )
    pflicht = _pflichtstellen(_entwurf(), bericht)
    assert "Bild 2" in pflicht and "Felsnische" in pflicht
    assert "Bild 3" not in pflicht


def test_der_kontaktbogen_zeigt_alle_bilder(tmp_path):
    bilder = []
    for nummer in range(5):
        pfad = tmp_path / f"{nummer}.png"
        Image.new("RGB", (1080, 1350), (nummer * 40, 20, 20)).save(pfad)
        bilder.append(pfad)
    bogen = kontaktbogen(bilder, tmp_path / "bogen.jpg")
    breite, hoehe = Image.open(bogen).size
    assert breite > 4 * 300 and hoehe > 2 * 375


def _agent_mit(entwurf: PostDraft):
    from insta_agent.runner import Agent

    agent = object.__new__(Agent)
    stand = {"draft": entwurf.model_dump_json()}
    agent.store = SimpleNamespace(get_post=lambda i: {"draft_json": stand["draft"]})
    agent.geaendert = []

    def unterschrift(post_id, caption):
        agent.geaendert.append(("caption", caption))
        return {"ok": True}

    def text(post_id, stelle, neu, akzentwort=None):
        agent.geaendert.append((stelle, neu))
        return {"ok": True}

    agent.bildunterschrift_aendern = unterschrift
    agent.text_aendern = text
    return agent


def _bericht(*aenderungen) -> Schlussbericht:
    return Schlussbericht(sprache=4, roter_faden=4, bild_und_text=4, gestaltung=4, gesamt=4,
                          staerke="", aenderungen=list(aenderungen))


def test_ein_doppelter_satz_wird_gestrichen():
    agent = _agent_mit(_entwurf())
    umgesetzt = agent._setze_redaktion_um(
        1, None, _bericht(Aenderung(stelle=0, alt="Der doppelte Satz.", neu="", grund="")),
        letzte=4,
    )
    assert umgesetzt == 1
    _, caption = agent.geaendert[0]
    assert "doppelte" not in caption
    assert "\n\n\n" not in caption


def test_zu_lange_bildtexte_und_die_abschlusskarte_bleiben_unangetastet():
    agent = _agent_mit(_entwurf())
    lang = " ".join(["Wort"] * 15)
    umgesetzt = agent._setze_redaktion_um(
        1, None,
        _bericht(
            Aenderung(stelle=2, alt="x", neu=lang, grund=""),
            Aenderung(stelle=4, alt="x", neu="Kurz", grund=""),
            Aenderung(stelle=3, alt="x", neu="So alt ist die Farbe", grund=""),
        ),
        letzte=4,
    )
    assert umgesetzt == 1
    assert agent.geaendert == [(3, "So alt ist die Farbe")]


def test_die_zahl_einer_kennzahlkarte_bleibt_stehen():
    """Bei der Katzennebel-Karte verschwand die Zahl mit dem umformulierten Satz."""
    entwurf = _entwurf(karten=[
        Karte(text="7.500 Lichtjahre ist die Katze entfernt", layout="zahl"),
        Karte(text="So alt ist die Bemalung"),
    ])
    agent = _agent_mit(entwurf)
    umgesetzt = agent._setze_redaktion_um(
        1, entwurf,
        _bericht(Aenderung(stelle=2, alt="x", neu="So weit entfernt steht die Katze", grund="")),
        letzte=4,
    )
    assert umgesetzt == 0


def test_eine_kennzahlkarte_ohne_zahl_bekommt_sie_beim_schreiben():
    from insta_agent.imaging.gestalt import _ZAHL

    karte = Karte(text="Das Licht war 7.500 Jahre unterwegs", layout="zahl")
    assert _ZAHL.search(karte.text).group(0).startswith("7.500")
