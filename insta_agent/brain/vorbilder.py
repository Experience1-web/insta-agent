"""Vorbilder: wie erfolgreiche Wissens-Accounts ihre Beiträge bauen.

Die Marktrecherche fragt, wer das Feld besetzt und wo eine Lücke ist -
das braucht die Wochenstrategie. Beim Schreiben hilft etwas anderes: wie
die Besten es machen. Welcher erste Satz hält den Daumen an, wie ist ein
Karussell aufgebaut, das bis zum Ende gewischt wird, wie lang ist eine
Bildunterschrift, die gespeichert wird.

Das ändert sich langsam. Deshalb läuft es selten - alle zwei Wochen oder
wenn der Betreiber es anstößt - und das Ergebnis liegt dann bei jedem
Beitrag mit auf dem Schreibtisch.

Zwei Schritte wie bei der Marktrecherche: erst mit Websuche frei
recherchieren, dann mit dem kleinen Modell ordnen. Das Ordnen ist billig;
schlägt es fehl, wird die bezahlte Recherche nicht weggeworfen.
"""

from __future__ import annotations

import logging

from ..economy.ledger import BudgetExhausted, CycleBudgetExceeded
from ..llm import Brain
from ..models import Vorbilder
from .prompts import PERSONA, identity_block, with_context

log = logging.getLogger(__name__)


def beobachte_vorbilder(brain: Brain, *, identity=None) -> Vorbilder:
    """Recherchiert die Machart erfolgreicher Wissens-Accounts und ordnet sie."""
    recherche = brain.text(
        system=PERSONA,
        label="Vorbilder ansehen",
        task="research",
        web_search=True,
        prompt=with_context(
            identity_block(identity),
            f"""\
# Auftrag
Sieh dir an, wie die erfolgreichsten Instagram-Accounts arbeiten, die von
Entdeckungen, Funden und Wissenschaft leben - Archäologie, Natur und neue
Arten, Weltall, Technik, Medizin. Große wie @natgeo oder @nasa, aber vor
allem kleinere, schnell gewachsene Wissens-Accounts, gern auch
deutschsprachige.

Es geht nicht um den Markt, sondern um die Machart:

- Der erste Satz auf dem Bild: Welche Muster halten dort den Daumen an?
  Nenne je ein echtes oder typisches Beispiel.
- Karussells: Wie viele Bilder, was steht auf dem ersten, was auf dem
  letzten, wie wird zum Weiterwischen gebracht?
- Bildunterschriften: Wie lang, wie aufgebaut, wie mit Quellen umgegangen,
  welche Aufforderung am Ende?
- Was erkennbar nicht funktioniert oder übersättigt ist.

Du hast höchstens {brain.suchbudget} Suchanfragen - plane sie vorher.
Schreib dichten Fließtext. Wo du etwas nicht belegen kannst, sag es.""",
        ),
    )

    try:
        vorbilder = brain.structured(
            schema=Vorbilder,
            system=PERSONA,
            label="Vorbilder ordnen",
            task="routine",
            prompt=f"""\
Bring deine Recherche in die vorgegebene Struktur. Erfinde nichts dazu.
Unter `fuer_uns` stehen drei bis fünf Regeln, die dieser Account ab dem
nächsten Beitrag umsetzen kann - konkret, nicht "sei kreativ". Sie dürfen
nichts verlangen, was gegen die Belegpflicht verstößt: Jede Zahl bleibt
belegt, jede Deutung bleibt als Deutung gekennzeichnet.

# Deine Recherche
{recherche.text}

# Gefundene Quellen
{chr(10).join(recherche.sources) or "keine"}""",
        )
    except (BudgetExhausted, CycleBudgetExceeded):
        # Die Notbremse gilt auch hier - sie abzufangen hiesse, einen
        # Ausreisser weiterlaufen zu lassen.
        raise
    except Exception as exc:  # noqa: BLE001 - die Recherche war teuer
        log.warning("Vorbilder liessen sich nicht ordnen (%s), nutze den Rohtext", exc)
        vorbilder = Vorbilder(fuer_uns=[recherche.text[:600]])

    vorbilder.quellen = list(dict.fromkeys([*vorbilder.quellen, *recherche.sources]))
    return vorbilder


def vorbilder_block(vorbilder: Vorbilder | None) -> str:
    """Was beim Schreiben mit auf dem Tisch liegt - kurz, nur das Brauchbare."""
    if vorbilder is None or not (vorbilder.fuer_uns or vorbilder.einstiege):
        return ""
    teile = ["# Was bei den besten Wissens-Accounts funktioniert"]
    if vorbilder.fuer_uns:
        teile.append("Regeln für dich:\n" + "\n".join(f"- {r}" for r in vorbilder.fuer_uns))
    if vorbilder.einstiege:
        teile.append(
            "Einstiege, die dort tragen:\n" + "\n".join(f"- {e}" for e in vorbilder.einstiege[:5])
        )
    if vorbilder.vermeiden:
        teile.append("Was dort nicht funktioniert:\n" + "\n".join(f"- {v}" for v in vorbilder.vermeiden[:4]))
    teile.append(
        "Das sind Anregungen zur Machart, keine Vorlage zum Abschreiben - und sie "
        "stehen nie über der Belegpflicht."
    )
    return "\n\n".join(teile)


__all__ = ["beobachte_vorbilder", "vorbilder_block"]
