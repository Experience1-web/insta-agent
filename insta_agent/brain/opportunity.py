"""Die Frage, die sich der Agent regelmäßig stellt: lohnt sich das noch?

Er rechnet den erwarteten Ertrag seines jetzigen Kurses gegen das, was er
sonst tun könnte - und zieht die Wechselkosten ab. Ein Wechsel kostet die
aufgebaute Reichweite, und die war teuer.
"""

from __future__ import annotations

from ..llm import Brain
from ..models import OpportunityAssessment
from .prompts import PERSONA, identity_block, treasury_block, with_context


def assess_opportunities(
    brain: Brain,
    *,
    identity,
    treasury_state,
    follower_count: int,
    performance: str,
    wallet_hinweis: str,
    zyklen_seit_wechsel: int,
) -> OpportunityAssessment:
    return brain.structured(
        schema=OpportunityAssessment,
        system=PERSONA,
        label="Lohnt sich das noch",
        prompt=with_context(
            identity_block(identity),
            treasury_block(treasury_state),
            f"# Deine Reichweite\nFollower: {follower_count}\n{performance}",
            wallet_hinweis,
            f"# Wie lange du diesen Kurs schon fährst\n{zyklen_seit_wechsel} Zyklen seit der letzten Neuausrichtung.",
            """\
# Auftrag
Rechne nach, ob dein jetziger Kurs noch der beste ist.

Erst dein jetziger Weg: Was bringt er in den nächsten 90 Tagen, wenn du
einfach weitermachst? Rechne von deinen echten Zahlen aus hoch, nicht von
dem, was du dir wünschst. Bei null Followern ist die ehrliche Antwort oft
nahe null - dann schreib das hin.

Dann die Alternativen. Für jede gibst du an, was sie einbringt WENN sie
aufgeht, und wie wahrscheinlich das ist. Diese beiden Zahlen getrennt zu
nennen ist der Kern: Eine Idee mit 5 Prozent Chance auf 10.000 USD ist im
Mittel 500 USD wert, nicht 10.000. Wer das verwechselt, jagt Luftschlösser.

Dann die Wechselkosten. Ein Kurswechsel wirft weg, was du aufgebaut hast:
Follower, die wegen des alten Themas da sind, deine Wiedererkennbarkeit,
die Zeit bis wieder etwas läuft. Bei wenigen Followern ist das fast nichts,
bei vielen ist es viel. Beziffere es.

Deine Empfehlung:
- "weitermachen", wenn der jetzige Kurs nicht deutlich geschlagen wird.
  Das ist der Normalfall. Ein Wechsel muss sich lohnen, nicht bloß
  interessant aussehen.
- "ergaenzen", wenn sich eine Einnahmequelle zusätzlich aufsetzen lässt,
  ohne die Nische zu verlassen. Oft die beste Antwort: Du behältst dein
  Publikum und verdienst trotzdem mehr.
- "wechseln" nur, wenn die Alternative den jetzigen Weg im Erwartungswert
  deutlich schlägt UND du die Wechselkosten abgezogen hast. Häufiges
  Wechseln ist der sicherste Weg, nie Publikum aufzubauen - dann ist jeder
  einzelne Wechsel rational und die Summe ruinös.

Schätze nüchtern. Du planst mit diesen Zahlen weiter, also schadest du
zuerst dir selbst, wenn du sie schönst.

Halte dich an das, womit du Menschen nicht schadest: keine Versprechen auf
Gewinne, keine erfundenen Belege, nichts, was deine Leser ärmer macht als
sie vorher waren. So etwas bringt kurz Geld und kostet dich den Account.""",
        ),
    )
