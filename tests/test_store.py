"""Das Gedächtnis muss einen Neustart überstehen."""

from insta_agent.models import Identity
from insta_agent.store import Store


def test_identitaet_ueberlebt_den_neustart(tmp_path, draft):
    path = tmp_path / "memory.db"
    identity = Identity(
        agent_name="Mara Vogt",
        agent_why="Kurz, sprechbar, nicht nach Maschine klingend.",
        handle="beispiel",
        display_name="Beispiel",
        motto="Ein Satz, der trägt.",
        niche="Gewohnheiten",
        target_audience="Berufstätige zwischen 25 und 40",
        tone_of_voice="direkt, ohne Floskeln",
        visual_identity="dunkle Flächen, harte Typografie",
        content_pillars=["Gewohnheiten", "Fokus", "Rückschläge"],
        bio="Kleine Schritte, jeden Tag.",
        why_this_works="Die Nische ist groß, aber schlecht besetzt.",
    )

    first = Store(path)
    first.set_json("identity", identity)
    first.add_draft(draft, "/tmp/bild.png")
    first.close()

    second = Store(path)
    restored = second.get_model("identity", Identity)
    assert restored.motto == "Ein Satz, der trägt."
    assert len(second.pending_drafts()) == 1
    second.close()


def test_entwurf_wird_zu_veroeffentlichtem_beitrag(store, draft):
    post_id = store.add_draft(draft, "/tmp/bild.png")
    assert store.published_count() == 0

    store.mark_published(post_id, "ig-media-42")
    assert store.published_count() == 1
    assert store.pending_drafts() == []
    assert store.recent_posts()[0]["ig_media_id"] == "ig-media-42"


def test_kennzahlen_behalten_ihre_reihenfolge(store):
    for value in (100, 140, 195):
        store.record_insight("followers", value)
    assert store.latest_metric("followers") == 195
    assert [v for _, v in store.metric_history("followers")] == [100.0, 140.0, 195.0]


def test_zyklusnummer_zaehlt_hoch(store):
    assert store.next_cycle_number() == 1
    store.log("cycle", "erster Lauf", cycle=1)
    assert store.next_cycle_number() == 2
