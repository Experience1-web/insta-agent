"""Der Arbeitszyklus des Agenten.

Ein Zyklus ist ein Arbeitstag: nachsehen, was die Zahlen sagen, daraus
lernen, den Kurs nachziehen, etwas veröffentlichen und ab und zu darüber
nachdenken, wie der Account Geld verdienen soll.

Alles Wissen liegt zwischen den Zyklen in der SQLite-Datei. Der Agent kann
jederzeit angehalten und später fortgesetzt werden, ohne sein Gedächtnis zu
verlieren.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from .brain import (
    assess_opportunities,
    build_monetization_plan,
    create_post_draft,
    erneuere_bildsprache,
    finde_stoff,
    invent_identity,
    pruefe_beitrag,
    pruefe_nachbesserung,
    pruefe_gestaltung,
    reflect,
    run_market_research,
    ueberarbeite_beitrag,
    update_strategy,
)
from .config import Settings
from .economy.ledger import BudgetExhausted, CycleBudgetExceeded, Mode, Treasury
from .imaging import FEED, STORY, lege_hook_auf, render_post_image
from .imaging.generator import KontingentErschoepft, baue_generator
from .instagram import InstagramClient, Publisher
from .llm import Brain, ModelRefused
from .models import (
    CycleReport,
    Fund,
    Identity,
    Karte,
    MarketAnalysis,
    MonetizationPlan,
    OpportunityAssessment,
    PostDraft,
    Pruefbericht,
    Reflection,
    StrategyUpdate,
)
from .store import Store
from .wallet import hinweis_fuer_den_agenten

log = logging.getLogger(__name__)

KEY_IDENTITY = "identity"
KEY_STRATEGY = "strategy"
KEY_ANALYSIS = "market_analysis"
KEY_REFLECTION = "reflection"
KEY_MONETIZATION = "monetization_plan"
KEY_ASSESSMENT = "opportunity_assessment"
KEY_LAST_PIVOT = "last_pivot_cycle"
KEY_IDENTITY_HISTORY = "identity_history"
# Mit welchen Zahlen zuletzt reflektiert wurde - sind es dieselben, gibt
# es nichts Neues zu bedenken.
KEY_ZAHLEN_BEI_REFLEXION = "zahlen_bei_reflexion"
KEY_STRATEGIE_ZYKLUS = "strategie_zyklus"

# Wie oft der Kurs ohne neuen Anlass trotzdem ueberprueft wird.
STRATEGIE_EVERY = 7

# Wie oft die Machart der besten Wissens-Accounts neu angesehen wird. Sie
# aendert sich langsam; eine Recherche mit Websuche kostet etwa 15-30 Cent.
KEY_VORBILDER = "vorbilder"
KEY_VORBILDER_ZYKLUS = "vorbilder_zyklus"
VORBILDER_EVERY = 14

# Was sich am Profil über das Dashboard ändern lässt. Handle und
# Anzeigename gehören dazu, weil sie auf Instagram stehen; `agent_why`
# und `why_this_works` sind Begründungen und ändern nichts am Betrieb.
PROFILFELDER = (
    "handle",
    "display_name",
    "niche",
    "target_audience",
    "tone_of_voice",
    "visual_identity",
    "bio",
    "content_pillars",
)

# Recherche und Geschäftsplanung kosten Geld und ändern sich langsam -
# deshalb nicht in jedem Zyklus.
RESEARCH_EVERY = 7
MONETIZATION_EVERY = 14

# Wie oft der Agent prüft, ob sich sein Kurs noch lohnt.
ASSESS_EVERY = 5

# Ein Wechsel wirft die aufgebaute Reichweite weg. Er lohnt sich nur, wenn
# die Alternative den jetzigen Weg deutlich schlägt - nicht knapp.
PIVOT_FAKTOR = 2.0

# Mindestabstand zwischen zwei Neuausrichtungen. Ohne diese Sperre wäre
# jeder einzelne Wechsel für sich rational und die Summe ruinös: Ein
# Account, der ständig die Nische tauscht, baut nie Publikum auf.
PIVOT_MINDESTABSTAND = 10



# Woran sich ein Bild vom Fund selbst erkennen laesst: Es kommt aus der
# Originalquelle, aus der Studie oder von der Behoerde.
BILD_VOM_FUND = 10

# Ab so vielen Punkten beim Hinsehen zeigt ein Archivbild die Sache -
# "eine echte Aufnahme von etwas, das eng dazugehoert".
ZEIGT_DIE_SACHE_AB = 7


def _blickpunkte(gesehen: str) -> int:
    """Die Punkte aus "7/10: Beschreibung" - -1, wenn nicht hingesehen wurde."""
    kopf = (gesehen or "").split("/", 1)[0].strip()
    return int(kopf) if kopf.isdigit() else -1


# Woerter, die in jedem zweiten Satz stehen und nichts ueber ein Bild sagen.
FUELLWOERTER = {
    "diese", "dieser", "dieses", "wenn", "einer", "eine", "einen", "eines",
    "sich", "nicht", "sind", "wird", "wurde", "auch", "noch", "oder",
    "aber", "weil", "dass", "beim", "nach", "ueber", "über", "mit", "ihre",
    "seine", "sein", "hat", "haben", "kein", "keine", "mehr", "nur", "schon",
}


def _wortstaemme(text: str) -> set[str]:
    """Grob die Staemme der tragenden Woerter: "leuchtet" und "leuchten"
    werden beide "leuch". Kurze und Fuellwoerter tragen nichts."""
    return {
        wort[:5]
        for wort in re.findall(r"[a-zäöüß]+", (text or "").casefold())
        if len(wort) >= 4 and wort not in FUELLWOERTER
    }


def _passendstes_bild(bilder: list, kartentext: str, thema: str = "") -> int:
    """Welches der uebrigen Bilder am besten zu diesem Kartentext passt.

    Frueher kamen sie der Reihe nach auf die Karten, und eine Karte "Sie
    leuchtet nur, wenn man sie beruehrt" bekam womoeglich den Meeresgrund,
    waehrend das Bild vom gruenen Leuchten auf der naechsten landete.
    Verglichen wird mit dem, was beim Hinsehen beschrieben wurde.

    Woerter, die schon im Thema stehen, zaehlen wenig: "Koralle" steht in
    fast jeder Beschreibung und entscheidet nichts. "Leuchtet" auf der
    Karte und "leuchten" in der Beschreibung dagegen schon.

    Ohne Beschreibung, oder wenn nichts uebereinstimmt, bleibt es bei der
    Reihenfolge - das beste Bild zuerst.
    """
    gesucht = _wortstaemme(kartentext)
    if not gesucht:
        return 0
    allgemein = _wortstaemme(thema)
    punkte = [
        sum(
            0.3 if stamm in allgemein else 1.0
            for stamm in gesucht & _wortstaemme(getattr(bild, "gesehen", ""))
        )
        for bild in bilder
    ]
    beste = max(punkte, default=0)
    return punkte.index(beste) if beste > 0 else 0


@dataclass(slots=True)
class Bildprobe:
    """Was die Bildsuche zu einem Fund ergeben hat, bevor der Text entsteht."""

    echt: Path | None
    nachweis: str
    quellbilder: list
    bildthema: str
    stufe: int | None
    """BILD_VOM_FUND, Punkte beim Hinsehen, -1 ungeprueft, None nichts."""

    @property
    def zeigt_die_sache(self) -> bool:
        if self.echt is None or self.stufe is None:
            return False
        # Ungeprueft laesst sich nicht beurteilen - dann gilt das Foto.
        return self.stufe < 0 or self.stufe >= ZEIGT_DIE_SACHE_AB

class Agent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = Store(settings.db_path)
        self.treasury = Treasury(self.store, settings.economy)

        from .economy.abrechnung import baue_abrechnung

        # Ohne brauchbaren Schlüssel bleibt es beim Schätzen - kein Fehler,
        # nur ungenauer.
        self.abrechnung = baue_abrechnung(settings.abrechnung_schluessel)
        self.brain = Brain(settings.llm, self.treasury, settings.anthropic_api_key)

        self.ig: InstagramClient | None = None
        if settings.instagram_ready:
            self.ig = InstagramClient(settings.ig_user_id, settings.ig_access_token)

        from .instagram.ablage import baue_ablagen

        # Mehrere Bildspeicher, nicht einer: Meta holt von manchen Adressen
        # nicht ab, und das laesst sich vorher nicht pruefen.
        self.ablagen = baue_ablagen(settings.ablage_anbieter, settings.ablage_token)
        self.ablage = self.ablagen[0] if self.ablagen else None
        self.publisher = Publisher(
            client=self.ig,
            media_dir=settings.media_dir,
            draft_dir=settings.draft_dir,
            public_base_url=settings.public_media_base_url,
            live=settings.posting.live,
            ablagen=self.ablagen,
        )

        # Ohne Schlüssel bleibt es bei der Typografie - kein Fehler, nur weniger.
        self.bildgenerator = baue_generator(
            settings.bild.anbieter,
            settings.bild.token,
            settings.bild.modell,
            art=settings.bild.art,
        )

        # Zustand der Bildsuche. Gesetzt wird er im Zyklus - aber die
        # Knöpfe im Dashboard ("dieses neu", "Bild neu") bauen einen
        # frischen Agenten ohne Zyklus. Fehlte das hier, stürzte "dieses
        # neu" ab, sobald eine Karte gemalt werden sollte.
        self._bilder_heute_aus: str | None = None
        self._bildthema = ""
        self._quellbilder: list = []
        # Fingerabdrücke der Bilder, die dieser Beitrag schon hat oder
        # hatte - "Bild neu" soll etwas anderes bringen, nicht dasselbe.
        self._ausschluss: list[int] = []
        self._benutzte_abdruecke: list[int] = []

    def _abdruecke_des_beitrags(self, post_id: int, zeile=None) -> list[int]:
        """Alles, was dieser Beitrag schon an Bildern hatte - samt dem jetzigen."""
        from .imaging.abdruck import abdruck

        bekannt = list(self.store.get_json(f"abdruecke:{post_id}") or [])
        zeile = zeile if zeile is not None else self.store.get_post(post_id)
        if zeile is not None and zeile["rohbild_path"]:
            if (jetzt := abdruck(zeile["rohbild_path"])) is not None:
                bekannt.append(jetzt)
        return bekannt

    def _merke_abdruecke(self, post_id: int, *pfade) -> None:
        """Hängt die Abdrücke neuer Bilder an die Liste dieses Beitrags an."""
        from .imaging.abdruck import abdruck

        bekannt = list(self.store.get_json(f"abdruecke:{post_id}") or [])
        neu = [a for p in pfade if p and (a := abdruck(p)) is not None]
        neu += list(self._benutzte_abdruecke)
        self._benutzte_abdruecke = []
        if neu:
            self.store.set_json(f"abdruecke:{post_id}", list(dict.fromkeys(bekannt + neu)))

    def _bildthema_fuer(self, fund) -> str:
        """Worum es auf allen Bildern gehen muss - der Fund, nicht ein Suchwort."""
        return " - ".join(
            teil
            for teil in (getattr(fund, "bildsuche", ""), getattr(fund, "titel", ""))
            if teil
        )

    def close(self) -> None:
        if self.ig:
            self.ig.close()
        if self.abrechnung is not None:
            self.abrechnung.close()
        if self.bildgenerator is not None and hasattr(self.bildgenerator, "close"):
            self.bildgenerator.close()
        self.store.close()

    # -- Zustand laden -----------------------------------------------------

    @property
    def identity(self) -> Identity | None:
        return self.store.get_model(KEY_IDENTITY, Identity)

    @property
    def strategy(self) -> StrategyUpdate | None:
        return self.store.get_model(KEY_STRATEGY, StrategyUpdate)

    @property
    def analysis(self) -> MarketAnalysis | None:
        return self.store.get_model(KEY_ANALYSIS, MarketAnalysis)

    @property
    def reflection(self) -> Reflection | None:
        return self.store.get_model(KEY_REFLECTION, Reflection)

    @property
    def monetization(self) -> MonetizationPlan | None:
        return self.store.get_model(KEY_MONETIZATION, MonetizationPlan)

    @property
    def assessment(self) -> OpportunityAssessment | None:
        return self.store.get_model(KEY_ASSESSMENT, OpportunityAssessment)

    @property
    def wallet_hinweis(self) -> str:
        return hinweis_fuer_den_agenten(
            self.settings.wallet_address, self.settings.wallet_chain
        )

    # -- Kennzahlen --------------------------------------------------------

    def collect_metrics(self, cycle: int) -> str:
        """Holt die aktuellen Zahlen und schreibt sie ins Gedächtnis."""
        if not self.ig:
            published = self.store.published_count()
            note = (
                "Kein Instagram-Zugang hinterlegt - es gibt keine echten Zahlen. "
                f"Bisher erstellt: {published} veröffentlichte Beiträge laut eigenem Protokoll. "
                "Plane so, als startest du bei null, und baue bewusst Varianten, "
                "die sich später unterscheiden lassen."
            )
            # Auch das Fehlen von Zahlen gehört ins Protokoll - sonst ist
            # später nicht nachvollziehbar, warum der Agent blind geplant hat.
            self.store.log("metrics", "Keine Kennzahlen verfügbar (kein Zugang)", cycle)
            return note

        lines: list[str] = []
        try:
            snapshot = self.ig.account()
            self.store.record_insight("followers", snapshot.followers)
            self.store.record_insight("media_count", snapshot.media_count)
            history = self.store.metric_history("followers", limit=8)
            trend = ""
            if len(history) >= 2:
                delta = history[-1][1] - history[0][1]
                trend = f" ({delta:+.0f} seit {len(history)} Messungen)"
            lines.append(f"Follower: {snapshot.followers}{trend}")
            lines.append(f"Beiträge: {snapshot.media_count}")
        except Exception as exc:  # Zahlen sind wichtig, aber kein Grund abzubrechen
            log.warning("Kontodaten nicht abrufbar: %s", exc)
            lines.append(f"Kontodaten nicht abrufbar: {exc}")

        for metric, value in (self.ig.account_insights() or {}).items():
            self.store.record_insight(metric, value)
            lines.append(f"{metric}: {value:.0f}")

        # Kennzahlen der zuletzt veröffentlichten Beiträge.
        for row in self.store.recent_posts(limit=5):
            if row["status"] != "published" or not row["ig_media_id"]:
                continue
            insights = self.ig.media_insights(row["ig_media_id"])
            for metric, value in insights.items():
                self.store.record_insight(metric, value, row["ig_media_id"])
            if insights:
                summary = ", ".join(f"{k}: {v:.0f}" for k, v in insights.items())
                lines.append(f"Beitrag {row['id']} ({row['pillar']}): {summary}")

        self.store.log("metrics", "Kennzahlen erfasst", cycle, payload=lines)
        return "\n".join(lines) if lines else "Noch keine Kennzahlen verfügbar."

    def _post_history(self) -> str:
        rows = self.store.recent_posts(limit=8)
        if not rows:
            return "Noch nichts veröffentlicht."
        return "\n".join(
            f"- [{r['status']}] {r['pillar']}: {r['caption'][:110].strip()}" for r in rows
        )

    # -- Einmalige Geburt --------------------------------------------------

    def neu_erfinden(self) -> list[str]:
        """Löscht, was der Agent über sich entschieden hat.

        Der nächste Zyklus fängt dann bei der Marktanalyse an und sucht
        sich Nische, Name und Bildsprache neu. Veröffentlichte Beiträge,
        Kasse und Journal bleiben stehen - sie sind seine Geschichte, und
        die Kasse ist ohnehin echtes Geld.
        """
        geloescht = []
        for schluessel in (
            KEY_IDENTITY,
            KEY_STRATEGY,
            KEY_ANALYSIS,
            KEY_REFLECTION,
            KEY_ASSESSMENT,
        ):
            if self.store.get_json(schluessel) is not None:
                self.store.set_json(schluessel, None)
                geloescht.append(schluessel)

        # Entwürfe aus der alten Nische passen nicht mehr zum neuen Profil.
        # Stehen blieben sie auf "wartet auf dich" - ein Fehlklick auf
        # Freigeben würde sie unter der neuen Identität veröffentlichen.
        verworfen = self.store.verwirf_alle_offenen()
        if verworfen:
            geloescht.append(f"{verworfen} offene Entwürfe")

        self.store.log("identity", "Der Agent fängt von vorne an und sucht sich eine neue Nische")
        return geloescht

    def bootstrap(self, *, operator_hint: str | None = None, cycle: int = 0) -> Identity:
        """Der Account wird eingerichtet. Passiert genau einmal.

        Im Regelfall übernimmt er dabei das vorgegebene Profil. Zweimal
        hat er sich vorher selbst eine Nische gesucht, und zweimal hat er
        sich auf ein einziges Gebiet festgelegt - erst Alltagsannahmen,
        dann Tiefsee. Wer eine Nische erfinden soll, wählt eine enge,
        weil enge sich besser begründen lassen. Gewollt ist aber ein
        Kriterium, kein Fach.

        Mit `identitaet_frei` sucht er wieder selbst. Das kostet dann
        eine Marktrecherche mehr und endet erfahrungsgemäß wieder in
        einer Sparte.
        """
        if existing := self.identity:
            return existing

        if not self.settings.posting.identitaet_frei:
            from .vorgabe import vorgegebene_identitaet

            identity = vorgegebene_identitaet()
            self.store.set_json(KEY_IDENTITY, identity)
            self.store.log(
                "identity",
                f"Profil übernommen: @{identity.handle} - {identity.motto}",
                cycle,
                payload=identity.model_dump(mode="json"),
            )
            log.info("Vorgegebenes Profil übernommen: @%s", identity.handle)
            return identity

        log.info("Kein Profil vorhanden - der Agent erfindet sich selbst")

        # Bricht der erste Lauf nach der Recherche ab, ist sie trotzdem
        # bezahlt und gespeichert. Sie dann beim nächsten Versuch erneut
        # einzukaufen, wäre das Geld zweimal ausgegeben.
        analysis = self.analysis
        if analysis is None:
            analysis = run_market_research(self.brain, identity=None, focus=operator_hint)
            self.store.set_json(KEY_ANALYSIS, analysis)
        else:
            log.info("Recherche aus dem Gedächtnis übernommen, spart einen teuren Aufruf")

        identity = invent_identity(self.brain, analysis, operator_hint=operator_hint)
        self.store.set_json(KEY_IDENTITY, identity)
        self.store.log(
            "identity",
            f"Der Agent nennt sich @{identity.handle} mit dem Motto: {identity.motto}",
            cycle,
            payload=identity.model_dump(mode="json"),
        )
        return identity

    def _kasse_nachfuehren(self) -> None:
        """Den Kontostand aus der echten Abrechnung fortschreiben.

        Vor jedem Zyklus, denn daran hängen Sparbetrieb und Stopp. Schlägt
        es fehl, wird weitergearbeitet: Eine nicht erreichbare Abrechnung
        ist kein Grund, den Tag ausfallen zu lassen - dann gelten eben die
        geschätzten Zahlen wie vorher.
        """
        if self.abrechnung is None:
            return
        try:
            differenz = self.treasury.aus_abrechnung(self.abrechnung)
        except Exception as exc:  # noqa: BLE001 - der Grund gehört ins Protokoll
            log.warning("Kasse nicht nachgefuehrt: %s", exc)
            return
        if differenz:
            log.info(
                "Kasse nachgefuehrt: %+.4f USD, Stand %.2f USD",
                differenz,
                self.treasury.state().balance_usd,
            )

    # -- Ein Zyklus --------------------------------------------------------

    def run_cycle(
        self, *, operator_hint: str | None = None, nur_beenden: bool = False
    ) -> CycleReport:
        """Ein vollstaendiger Zyklus - oder nur sein zweiter Teil.

        `nur_beenden` ist fuer den Fall, dass die Zyklusgrenze mitten im
        Lauf gegriffen hat. Dann ist die teure Vorarbeit schon getan und
        bezahlt: Reflexion, Marktrecherche und Kurs stehen im Speicher.
        Sie noch einmal zu denken, waere das Geld ein zweites Mal aus dem
        Fenster - und ein anderes Ergebnis obendrein.

        Also wird nur nachgeholt, was fehlt: die Beitraege selbst.
        """
        cycle = self.store.next_cycle_number()
        report = CycleReport(started_at=datetime.now(timezone.utc))
        self.treasury.begin_cycle()
        self._kasse_nachfuehren()
        # Gilt nur fuer diesen Lauf: Morgen ist das Kontingent wieder da.
        self._bilder_heute_aus: str | None = None

        try:
            if nur_beenden:
                self._beende_zyklus_inner(cycle, report)
            else:
                self._run_cycle_inner(cycle, report, operator_hint)
        except BudgetExhausted as exc:
            report.halted_reason = str(exc)
            self.store.log("halt", str(exc), cycle)
            log.error("%s", exc)
        except CycleBudgetExceeded as exc:
            report.halted_reason = str(exc)
            self.store.log("budget", str(exc), cycle)
            log.warning("%s", exc)
        except ModelRefused as exc:
            report.halted_reason = str(exc)
            self.store.log("refusal", str(exc), cycle)
            log.error("%s", exc)
        except anthropic.APIStatusError as exc:
            # Fehler der Gegenseite in Klartext übersetzen - ein roher
            # Traceback sagt niemandem, dass nur das Guthaben fehlt.
            erklaerung = _erklaere_api_fehler(exc)
            report.halted_reason = erklaerung
            self.store.log("api_error", erklaerung, cycle, payload={"status": exc.status_code})
            log.error("%s", erklaerung)
        except anthropic.APIConnectionError as exc:
            erklaerung = (
                "Keine Verbindung zur Claude API. Prüfe deine Internetverbindung "
                f"und versuch es gleich nochmal. ({exc})"
            )
            report.halted_reason = erklaerung
            self.store.log("api_error", erklaerung, cycle)
            log.error("%s", erklaerung)

        report.finished_at = datetime.now(timezone.utc)
        report.cost_usd = self.treasury.state().cycle_spent_usd
        self.store.log(
            "cycle",
            f"Zyklus {cycle} beendet, Kosten {report.cost_usd:.4f} USD",
            cycle,
            payload=report.model_dump(mode="json"),
        )
        return report

    def _run_cycle_inner(
        self, cycle: int, report: CycleReport, operator_hint: str | None
    ) -> None:
        state = self.treasury.check()
        report.steps.append(f"Kasse: {state.balance_usd:.4f} USD ({state.mode.value})")

        identity = self.bootstrap(operator_hint=operator_hint, cycle=cycle)
        report.steps.append(f"Profil: @{identity.handle} - {identity.motto}")

        performance = self.collect_metrics(cycle)
        report.steps.append("Kennzahlen erfasst")

        # Reflektieren, wenn es etwas Neues zu bedenken gibt - nicht in
        # jedem Zyklus. Solange Instagram keine Kennzahlen herausgibt, sind
        # es jedes Mal dieselben Saetze, und die Reflexion lief trotzdem,
        # mit dem teuersten Modell, und kam zu denselben Schluessen. Das
        # war ein gutes Zehntel jedes Beitrags fuer nichts.
        reflection = self.reflection
        if reflection is not None and self.store.get_json(KEY_ZAHLEN_BEI_REFLEXION) is None:
            # Stand von vor dieser Regel: Es gibt eine Reflexion, aber keine
            # Notiz, auf welchen Zahlen sie beruht. Dann gilt sie für die
            # jetzigen - sonst liefe sie nach jedem Update einmal umsonst.
            self.store.set_json(KEY_ZAHLEN_BEI_REFLEXION, performance)
        neue_zahlen = performance != (self.store.get_json(KEY_ZAHLEN_BEI_REFLEXION) or "")
        reflektiert = False
        if self.store.published_count() > 0 and (neue_zahlen or reflection is None):
            reflection = reflect(
                self.brain,
                identity=identity,
                strategy=self.strategy,
                performance=performance,
                post_history=self._post_history(),
            )
            self.store.set_json(KEY_REFLECTION, reflection)
            self.store.set_json(KEY_ZAHLEN_BEI_REFLEXION, performance)
            report.steps.append("Reflexion abgeschlossen")
            reflektiert = True
        elif self.store.published_count() > 0:
            report.steps.append("Reflexion übersprungen - keine neuen Zahlen seit der letzten")

        # Recherche kostet - nur in festem Takt oder wenn der Kurs wackelt.
        # Der Kurs wackelt nur, wenn gerade neu reflektiert wurde; eine
        # alte Reflexion hat ihre Recherche schon bekommen.
        analysis = self.analysis
        due = cycle % RESEARCH_EVERY == 0
        wants_change = bool(reflektiert and reflection and reflection.strategy_should_change)
        recherchiert = False
        if (due or wants_change) and state.mode is Mode.NORMAL:
            analysis = run_market_research(self.brain, identity=identity)
            self.store.set_json(KEY_ANALYSIS, analysis)
            report.steps.append(f"Marktrecherche ({len(analysis.sources)} Quellen)")
            recherchiert = True

        # Den Kurs neu bestimmen, wenn es einen Anlass gibt: neue
        # Reflexion, neue Recherche, noch gar kein Kurs - oder eine Woche
        # ohne Ueberpruefung. Sonst gilt der bisherige; ihn jedes Mal mit
        # dem teuersten Modell neu herzuleiten, ergab denselben Kurs.
        strategy = self.strategy
        letzte = self.store.get_json(KEY_STRATEGIE_ZYKLUS)
        if strategy is not None and not isinstance(letzte, int):
            # Ebenso: Ein Kurs ist da, nur nicht, seit wann. Er zählt ab jetzt.
            letzte = cycle
            self.store.set_json(KEY_STRATEGIE_ZYKLUS, cycle)
        faellig = not isinstance(letzte, int) or cycle - letzte >= STRATEGIE_EVERY
        if strategy is None or reflektiert or recherchiert or faellig:
            strategy = update_strategy(
                self.brain,
                identity=identity,
                previous=self.strategy,
                analysis=analysis,
                reflection=reflection,
                performance=performance,
                treasury_state=self.treasury.state(),
            )
            self.store.set_json(KEY_STRATEGY, strategy)
            self.store.set_json(KEY_STRATEGIE_ZYKLUS, cycle)
            report.steps.append(f"Ziel: {strategy.current_goal}")
        else:
            report.steps.append(f"Kurs unverändert: {strategy.current_goal}")

        # Lohnt sich der Kurs noch? Nicht in jedem Zyklus - das kostet.
        if cycle % ASSESS_EVERY == 0 and state.mode is Mode.NORMAL:
            identity = self._pruefe_kurs(cycle, identity, performance, report)

        # Das Handwerk der Besten, selten nachgesehen - es liegt danach bei
        # jedem Beitrag mit auf dem Schreibtisch.
        letzte_vorbilder = self.store.get_json(KEY_VORBILDER_ZYKLUS)
        if state.mode is Mode.NORMAL and (
            self.vorbilder is None
            or not isinstance(letzte_vorbilder, int)
            or cycle - letzte_vorbilder >= VORBILDER_EVERY
        ):
            self._sieh_vorbilder_an(identity, report, cycle)

        self._veroeffentliche_freigegebenes(report)
        self._produce_posts(cycle, identity, strategy, performance, report)

        # Geschäftsplanung in großem Takt - oder sofort, wenn das Geld knapp wird.
        if cycle % MONETIZATION_EVERY == 0 or self.treasury.state().mode is Mode.FRUGAL:
            self._plan_monetization(cycle, identity, performance, report)

    def _beende_zyklus_inner(self, cycle: int, report: CycleReport) -> None:
        """Holt nach, was der abgebrochene Zyklus nicht mehr geschafft hat.

        Bewusst ohne Reflexion, Marktrecherche, Kursbestimmung und
        Geschaeftsplanung: Die haben beim ersten Anlauf stattgefunden und
        liegen im Speicher. Was fehlt, sind die Beitraege.

        Ohne Kurs geht es nicht - dann hat der Zyklus so frueh abgebrochen,
        dass es nichts fortzusetzen gibt, und ein normaler Lauf ist das
        Richtige.
        """
        state = self.treasury.check()
        report.steps.append(f"Kasse: {state.balance_usd:.4f} USD ({state.mode.value})")

        identity = self.identity
        strategy = self.strategy
        if identity is None or strategy is None:
            report.halted_reason = (
                "Es liegt noch kein Kurs vor - da ist nichts fortzusetzen. "
                "Starte einen normalen Zyklus."
            )
            return

        report.steps.append(
            f"Fortsetzung ohne neue Vorarbeit - Kurs steht: {strategy.current_goal}"
        )

        performance = self.collect_metrics(cycle)
        self._veroeffentliche_freigegebenes(report)
        self._produce_posts(cycle, identity, strategy, performance, report)

    def _produce_posts(
        self, cycle: int, identity, strategy, performance: str, report: CycleReport
    ) -> None:
        recent = [r["caption"] for r in self.store.recent_posts(limit=8)]

        for index in range(max(self.settings.posting.posts_per_day, 1)):
            try:
                self.treasury.check()
            except (BudgetExhausted, CycleBudgetExceeded) as exc:
                # Reicht es nicht einmal für den ersten Beitrag, hält der
                # Zyklus an - das soll oben im Bericht stehen, nicht nur
                # als Randnotiz.
                if index == 0:
                    raise
                report.steps.append(f"Weitere Posts abgebrochen: {exc}")
                break

            # Was dieser eine Beitrag kostet, vom Stand vor dem ersten
            # Aufruf bis zum letzten. Die Kasse kennt nur die Summe des
            # Zyklus; was ein einzelner Beitrag gekostet hat, ist aber die
            # Zahl, an der sich entscheidet, ob er sein Geld wert war.
            stand_vorher = self.treasury.state().cycle_spent_usd

            # Erst der Stoff, dann der Text. Andersherum schreibt der
            # Agent über das, was ihm einfällt - und was einem einfällt,
            # ist der eigene Alltag.
            fund = self._suche_stoff(report)
            draft = create_post_draft(
                self.brain,
                identity=identity,
                strategy=strategy,
                recent_captions=recent,
                max_hashtags=self.settings.posting.max_hashtags,
                performance_note=performance,
                fund=fund,
                persona=self._persona_chef(),
                vorbilder=self.vorbilder,
            )
            if not draft.visual.footer.strip():
                draft.visual.footer = f"@{identity.handle}"

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            basis = f"{stamp}-{cycle}-{index}"

            # Immer zuerst die typografische Fassung. Sie kostet nichts und
            # ist die Rückfallebene, wenn der Bilddienst streikt - so steht
            # am Ende jedes Zyklus ein fertiger Beitrag, nie eine Lücke.
            image_path = render_post_image(
                draft.visual,
                self.settings.media_dir / f"{basis}.png",
                groesse=self._bildformat,
            )
            # Erst die Bildsprache, dann malen: Was zählt, ist der Prompt.
            # Ein Urteil über ein fertiges Bild käme zu spät, um noch etwas
            # zu ändern - und ein zweites Bild kostet zweimal.
            # Die Bildsprache verbessert die Vorlage fuers Malen. Liegt
            # schon ein echtes Foto bereit, wird nicht gemalt - dann waere
            # sie bezahlte Arbeit fuer nichts, samt Websuche.
            probe = getattr(self, "_bildproben", {}).get(id(fund)) if fund is not None else None
            if probe is not None and probe.echt is not None:
                gestaltung = None
                report.steps.append("Bildsprache übersprungen - es gibt ein echtes Foto")
            else:
                gestaltung = self._gestalte(draft, identity, report)
            erzeugt, rohbild = self._erzeuge_bild(draft, basis, identity, report, fund)
            if erzeugt:
                image_path = erzeugt
            post_id = self.store.add_draft(draft, str(image_path))
            self.store.setze_rohbild(post_id, str(rohbild) if rohbild else None)
            self.store.setze_bildnachweis(post_id, getattr(self, "_letzter_nachweis", ""))
            if fund is not None:
                self.store.set_fund(post_id, fund)
            if gestaltung is not None:
                self.store.set_gestaltung(post_id, gestaltung)
            # Die weiteren Bilder zum Durchwischen. Erst jetzt, nach dem
            # ersten Bild: Sie richten sich in Farbe und Stil danach.
            self._benutzte_abdruecke = []
            self._letzte_kartenroh = []
            weitere, karten_nachweise, ersatz = self._baue_karussell(
                draft, basis, identity, report, erstes_roh=rohbild
            )
            self._merke_abdruecke(post_id, rohbild)
            if weitere:
                roh_liste = list(self._letzte_kartenroh or [])
                self._speichere_bildstand(post_id, {
                    "titel": [],
                    "karten": [
                        {"roh": roh_liste[i] if i < len(roh_liste) else None, "verlauf": []}
                        for i in range(len(weitere))
                    ],
                })
            # Was aus der Quelle uebrig ist, gehoert zu diesem Beitrag und
            # zu keinem anderen. Liegen gelassen, taucht es sonst beim
            # naechsten "Bild neu" in einem fremden Beitrag auf.
            self._quellbilder = []
            if ersatz is not None:
                # Ein zerschnittenes Panorama: Das Hauptbild ist jetzt das
                # linke Stueck, nicht die ganze Aufnahme.
                image_path = ersatz
                self.store.setze_bildpfad(post_id, str(ersatz))
            if weitere:
                self.store.setze_karussell(post_id, [str(b) for b in weitere])
                if karten_nachweise:
                    schon = getattr(self, "_letzter_nachweis", "")
                    alle = [t for t in [schon, *karten_nachweise] if t]
                    self.store.setze_bildnachweis(post_id, " · ".join(dict.fromkeys(alle)))

            bericht = self._pruefe(post_id, draft, identity, report, fund)
            bericht = self._bessere_nach(post_id, bericht, report)

            # Zum Schluss das Reel - nach dem Nachbessern, damit es die
            # fertigen Bilder zeigt. Kostet nichts; fehlt ffmpeg, eben nicht.
            if weitere:
                reel = self.reel_bauen(post_id)
                report.steps.append(
                    "Reel gebaut" if reel["ok"] else f"Kein Reel: {reel['grund']}"
                )

            kosten = self.treasury.state().cycle_spent_usd - stand_vorher
            self.store.setze_kosten(post_id, kosten)
            report.steps.append(f"Beitrag fertig, Kosten {kosten:.4f} USD")

            if zeile := self.store.get_post(post_id):
                # Nach einer Nachbesserung steht dort ein anderes Bild.
                image_path = Path(zeile["image_path"] or image_path)

            report.drafts_written.append(str(image_path))
            if self.settings.posting.freigabe_noetig:
                # Der Normalfall: Der Beitrag wartet auf das Ja des
                # Betreibers. Erst der nächste Zyklus schickt raus, was
                # freigegeben wurde.
                report.steps.append(f"Entwurf {post_id} wartet auf Freigabe")
            elif bericht is not None and not bericht.darf_raus:
                # Autopilot, aber die Endprüfung hat etwas gefunden. Dann
                # entscheidet ein Mensch - dafür ist die Prüfung da.
                report.steps.append(
                    f"Entwurf {post_id} von der Endprüfung angehalten: {bericht.urteil}"
                )
            else:
                # Autopilot: Der Betreiber hat die Freigabepflicht
                # abgeschaltet. Dann geht der Beitrag mit dem nächsten
                # Zyklus von selbst hinaus.
                self.store.freigeben(post_id)
                report.steps.append(f"Entwurf {post_id} automatisch freigegeben")

            recent.append(draft.caption)

    def _mitrechnen(self, post_id: int, vorher: float) -> float:
        """Bucht auf den Beitrag, was seit `vorher` fuer ihn ausgegeben wurde.

        Nachbessern, nachpruefen und ein neues Bild kosten erneut. Wer
        spaeter fragt, was ein Beitrag gekostet hat, meint alles davon -
        nicht nur den ersten Anlauf.
        """
        kosten = self.treasury.state().cycle_spent_usd - vorher
        if kosten > 0:
            self.store.setze_kosten(post_id, kosten)
        return kosten

    def karte_neu(self, post_id: int, stelle: int) -> dict:
        """Erneuert ein einzelnes Bild eines Karussells, nicht den ganzen Satz.

        `stelle` ist die Position beim Wischen: 1 ist das erste Bild, dafuer
        gilt weiterhin `bild_neu`. Ab 2 geht es um eine Karte.

        Das ist der Unterschied, auf den es ankommt: Wenn von fuenf Bildern
        eines misslungen ist, will man dieses eine tauschen und nicht vier
        gelungene mit. Die uebrigen bleiben unberuehrt, auch in der Farbe -
        ein einzelnes Bild wird dem ersten angeglichen, nicht die Reihe neu
        aufeinander eingestellt.
        """
        zeile = self.store.get_post(post_id)
        if zeile is None:
            return {"ok": False, "grund": "Diesen Entwurf gibt es nicht."}
        if zeile["status"] != "draft":
            return {"ok": False, "grund": "Nur bei einem Entwurf lässt sich das Bild tauschen."}
        if stelle <= 1:
            return self.bild_neu(post_id)

        identity = self.identity
        if identity is None:
            return {"ok": False, "grund": "Es gibt noch kein Profil."}

        bilder = json.loads(zeile["karussell_json"] or "[]")
        versatz = stelle - 2
        if not 0 <= versatz < len(bilder):
            return {"ok": False, "grund": f"Ein {stelle}. Bild gibt es hier nicht."}

        draft = PostDraft.model_validate(json.loads(zeile["draft_json"]))
        if versatz >= len(draft.karten):
            self._karten_wiederfinden(post_id, draft, len(bilder))
        if versatz >= len(draft.karten):
            return {
                "ok": False,
                "grund": "Zu diesem Bild gibt es keine Karte mehr - der Text dazu ist "
                "verloren gegangen. Verwerfen und neu schreiben lassen hilft.",
            }

        # Beurteilt wird das neue Bild gegen den Fund, nicht gegen das
        # Suchwort der Karte - sonst passt jede Grabung zu "excavation".
        if zeile["fund_json"]:
            self._bildthema = self._bildthema_fuer(
                Fund.model_validate(json.loads(zeile["fund_json"]))
            )

        self._ausschluss = self._abdruecke_des_beitrags(post_id, zeile)
        self._benutzte_abdruecke = []

        self.treasury.check()
        vorher = self.treasury.state().cycle_spent_usd
        roh = self._karte_erneuern(post_id, draft, bilder, versatz, identity)
        self._merke_abdruecke(post_id)
        kosten = self._mitrechnen(post_id, vorher)
        self.store.log(
            "bild_neu",
            f"Entwurf {post_id}: Bild {stelle} neu ({kosten:.4f} USD)",
        )
        return {"ok": True, "gemalt": roh is not None, "stelle": stelle, "schritte": []}

    def karte_entfernen(self, post_id: int, stelle: int) -> dict:
        """Nimmt ein Bild aus dem Karussell heraus - kostenlos.

        Manchmal gibt es für eine Karte kein passendes Bild, und ein
        falsches ist schlechter als keines: Die sowjetische Münze von 1923
        in einem Beitrag über Zarengold. Dann fällt die Karte weg. Das
        Titelbild bleibt immer.
        """
        zeile = self.store.get_post(post_id)
        if zeile is None:
            return {"ok": False, "grund": "Diesen Entwurf gibt es nicht."}
        if zeile["status"] != "draft":
            return {"ok": False, "grund": "Nur bei einem Entwurf lassen sich Bilder entfernen."}
        if stelle <= 1:
            return {"ok": False, "grund": "Das Titelbild bleibt - tauschen geht mit „Bild neu“."}
        bilder = json.loads(zeile["karussell_json"] or "[]")
        versatz = stelle - 2
        if not 0 <= versatz < len(bilder):
            return {"ok": False, "grund": f"Ein {stelle}. Bild gibt es hier nicht."}

        stand = self._bildstand(post_id, len(bilder))
        del bilder[versatz]
        del stand["karten"][versatz]
        self._speichere_bildstand(post_id, stand)
        self.store.setze_karussell(post_id, bilder)
        draft = PostDraft.model_validate(json.loads(zeile["draft_json"]))
        if versatz < len(draft.karten):
            del draft.karten[versatz]
            self.store.setze_entwurfsdaten(post_id, draft)
        self.store.log("bild_neu", f"Entwurf {post_id}: Bild {stelle} entfernt")
        return {"ok": True, "entfernt": stelle, "schritte": []}

    def _karte_erneuern(
        self, post_id: int, draft, bilder: list, versatz: int, identity, alte_karte=None
    ):
        """Holt das Bild einer Karte neu und beschriftet es - ohne zu buchen.

        Gebucht wird dort, wo der Auftrag herkommt: bei "dieses neu" für
        diese eine Karte, beim Nachbessern mit allem anderen zusammen.
        Gibt das Grundbild zurück, oder None, wenn es bei Schrift blieb.

        Das bisherige Bild kommt in den Verlauf - "vorheriges" holt es
        zurück, samt dem Text, der darauf stand.
        """
        self._karte_in_verlauf(post_id, bilder, versatz, alte_karte or draft.karten[versatz])
        stelle = versatz + 2
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        basis = f"{stamp}-neu-{post_id}"
        karte = draft.karten[versatz]
        roh, _nachweis = self._karte_rohbild(karte, basis, stelle)

        if roh is not None:
            from .imaging.angleichen import gleiche_an

            gleiche_an(
                roh,
                hintergrund_hex=draft.visual.background_hex,
                akzent_hex=draft.visual.accent_hex,
            )

        neues = self._beschrifte_karte(karte, roh, basis, stelle, draft, identity)
        bilder[versatz] = str(neues)
        self.store.setze_karussell(post_id, bilder)
        stand = self._bildstand(post_id, len(bilder))
        stand["karten"][versatz]["roh"] = str(roh) if roh else None
        self._speichere_bildstand(post_id, stand)
        return roh

    # --- Verlauf der Bilder und Texte von Hand ----------------------------

    VERLAUF_TIEFE = 10

    def _bildstand(self, post_id: int, anzahl_karten: int | None = None) -> dict:
        """Grundbilder und Verlauf eines Beitrags - Titelbild und jede Karte."""
        stand = self.store.get_json(f"bildstand:{post_id}") or {}
        stand.setdefault("titel", [])
        stand.setdefault("karten", [])
        if anzahl_karten is not None:
            while len(stand["karten"]) < anzahl_karten:
                stand["karten"].append({"roh": None, "verlauf": []})
        return stand

    def _speichere_bildstand(self, post_id: int, stand: dict) -> None:
        for eintrag in [stand.get("titel", []), *(k["verlauf"] for k in stand.get("karten", []))]:
            del eintrag[: max(0, len(eintrag) - self.VERLAUF_TIEFE)]
        self.store.set_json(f"bildstand:{post_id}", stand)

    def _karte_in_verlauf(self, post_id: int, bilder: list, versatz: int, karte) -> None:
        stand = self._bildstand(post_id, len(bilder))
        stand["karten"][versatz]["verlauf"].append({
            "bild": bilder[versatz],
            "roh": stand["karten"][versatz].get("roh"),
            "karte": karte.model_dump(mode="json") if karte is not None else None,
        })
        self._speichere_bildstand(post_id, stand)

    def _titel_in_verlauf(self, post_id: int, zeile, draft) -> None:
        stand = self._bildstand(post_id)
        stand["titel"].append({
            "bild": zeile["image_path"],
            "roh": zeile["rohbild_path"],
            "nachweis": zeile["bildnachweis"],
            "bildtext": draft.hook_text_on_screen,
        })
        self._speichere_bildstand(post_id, stand)

    def _kartenroh(self, post_id: int, versatz: int, bildpfad: str | None) -> Path | None:
        """Das Grundbild einer Karte - gemerkt, oder neben dem fertigen Bild gefunden.

        Ältere Beiträge haben keinen gemerkten Stand. Das Grundbild liegt
        aber meist noch da: "...-k3-echt.jpg" oder "...-k3-roh.png" neben
        dem fertigen "...-k3.png".
        """
        stand = self._bildstand(post_id)
        if versatz < len(stand["karten"]):
            if (roh := stand["karten"][versatz].get("roh")) and Path(roh).is_file():
                return Path(roh)
        if bildpfad:
            fertig = Path(bildpfad)
            for endung in ("-echt.jpg", "-roh.png"):
                kandidat = fertig.with_name(fertig.stem + endung)
                if kandidat.is_file():
                    return kandidat
        return None

    def verlauf_laengen(self, post_id: int) -> dict[str, int]:
        """Wie oft sich je Stelle zurückgehen lässt - für die Knöpfe im Dashboard."""
        stand = self._bildstand(post_id)
        laengen = {"1": len(stand["titel"])}
        for versatz, karte in enumerate(stand["karten"]):
            laengen[str(versatz + 2)] = len(karte.get("verlauf", []))
        return laengen

    def vorheriges_bild(self, post_id: int, stelle: int) -> dict:
        """Stellt das Bild an dieser Stelle so wieder her, wie es vorher war."""
        zeile = self.store.get_post(post_id)
        if zeile is None:
            return {"ok": False, "grund": "Diesen Entwurf gibt es nicht."}
        if zeile["status"] != "draft":
            return {"ok": False, "grund": "Nur bei einem Entwurf lässt sich etwas zurückholen."}
        draft = PostDraft.model_validate(json.loads(zeile["draft_json"]))
        bilder = json.loads(zeile["karussell_json"] or "[]")
        stand = self._bildstand(post_id, len(bilder))

        if stelle <= 1:
            if not stand["titel"]:
                return {"ok": False, "grund": "Für das Titelbild gibt es kein vorheriges."}
            alt = stand["titel"].pop()
            if not alt.get("bild") or not Path(alt["bild"]).is_file():
                self._speichere_bildstand(post_id, stand)
                return {"ok": False, "grund": "Die Datei des vorherigen Bildes gibt es nicht mehr."}
            self.store.setze_bildpfad(post_id, alt["bild"])
            self.store.setze_rohbild(post_id, alt.get("roh"))
            self.store.setze_bildnachweis(post_id, alt.get("nachweis"))
            if alt.get("bildtext") is not None and alt["bildtext"] != draft.hook_text_on_screen:
                draft.hook_text_on_screen = alt["bildtext"]
                self.store.setze_entwurfsdaten(post_id, draft)
        else:
            versatz = stelle - 2
            if not 0 <= versatz < len(bilder) or not stand["karten"][versatz]["verlauf"]:
                return {"ok": False, "grund": f"Für Bild {stelle} gibt es kein vorheriges."}
            alt = stand["karten"][versatz]["verlauf"].pop()
            if not alt.get("bild") or not Path(alt["bild"]).is_file():
                self._speichere_bildstand(post_id, stand)
                return {"ok": False, "grund": "Die Datei des vorherigen Bildes gibt es nicht mehr."}
            bilder[versatz] = alt["bild"]
            stand["karten"][versatz]["roh"] = alt.get("roh")
            self.store.setze_karussell(post_id, bilder)
            if alt.get("karte") and versatz < len(draft.karten):
                draft.karten[versatz] = Karte.model_validate(alt["karte"])
                self.store.setze_entwurfsdaten(post_id, draft)
        self._speichere_bildstand(post_id, stand)
        self.store.log("bild_neu", f"Entwurf {post_id}: Bild {stelle} zurückgeholt")
        return {"ok": True, "stelle": stelle}

    def text_aendern(
        self, post_id: int, stelle: int, text: str, akzentwort: str | None = None
    ) -> dict:
        """Setzt einen neuen Text auf dasselbe Bild - ohne Suche, ohne Kosten.

        Stelle 1 ist der Text auf dem Titelbild, ab 2 der Fakt auf einer
        Karte. Das Foto bleibt; nur die Schrift wird neu gesetzt. Die
        vorige Fassung kommt in den Verlauf.
        """
        text = " ".join((text or "").split())
        if not text:
            return {"ok": False, "grund": "Ein leerer Text geht nicht."}
        if len(text) > 160:
            return {"ok": False, "grund": "Das ist zu lang für ein Bild - höchstens 160 Zeichen."}
        zeile = self.store.get_post(post_id)
        if zeile is None:
            return {"ok": False, "grund": "Diesen Entwurf gibt es nicht."}
        if zeile["status"] != "draft":
            return {"ok": False, "grund": "Nur ein Entwurf lässt sich ändern."}
        identity = self.identity
        if identity is None:
            return {"ok": False, "grund": "Es gibt noch kein Profil."}
        draft = PostDraft.model_validate(json.loads(zeile["draft_json"]))
        akzent = (akzentwort or "").strip()
        if akzent and akzent.casefold() not in text.casefold():
            akzent = ""

        if stelle <= 1:
            if text == draft.bildtext and not akzent:
                return {"ok": True, "unveraendert": True}
            self._titel_in_verlauf(post_id, zeile, draft)
            neu = draft.model_copy(deep=True)
            neu.hook_text_on_screen = text
            if akzent:
                neu.visual.akzentwort = akzent
            bild, _wie = self._schrift_erneuern(zeile, neu, identity, post_id)
            self.store.setze_bildpfad(post_id, str(bild))
            self.store.setze_entwurfsdaten(post_id, neu)
        else:
            bilder = json.loads(zeile["karussell_json"] or "[]")
            versatz = stelle - 2
            if not 0 <= versatz < len(bilder):
                return {"ok": False, "grund": f"Ein {stelle}. Bild gibt es hier nicht."}
            if versatz >= len(draft.karten):
                self._karten_wiederfinden(post_id, draft, len(bilder))
            if versatz >= len(draft.karten):
                return {"ok": False, "grund": "Zu diesem Bild ist kein Text gespeichert."}
            alte = draft.karten[versatz]
            if text == alte.text and (not akzent or akzent == alte.akzentwort):
                return {"ok": True, "unveraendert": True}
            roh = self._kartenroh(post_id, versatz, bilder[versatz])
            self._karte_in_verlauf(post_id, bilder, versatz, alte)
            karte = alte.model_copy(update={"text": text, "akzentwort": akzent})
            draft.karten[versatz] = karte
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            neues = self._beschrifte_karte(
                karte, roh, f"{stamp}-text-{post_id}", stelle, draft, identity
            )
            bilder[versatz] = str(neues)
            self.store.setze_karussell(post_id, bilder)
            stand = self._bildstand(post_id, len(bilder))
            stand["karten"][versatz]["roh"] = str(roh) if roh else None
            self._speichere_bildstand(post_id, stand)
            self.store.setze_entwurfsdaten(post_id, draft)

        self._von_hand_geaendert(post_id)
        return {"ok": True, "stelle": stelle}

    def bildunterschrift_aendern(self, post_id: int, caption: str) -> dict:
        """Die Bildunterschrift von Hand - kostenlos, wie der Text auf den Bildern."""
        caption = (caption or "").strip()
        if not caption:
            return {"ok": False, "grund": "Eine leere Bildunterschrift geht nicht."}
        if len(caption) > 2200:
            return {"ok": False, "grund": "Instagram erlaubt höchstens 2.200 Zeichen."}
        zeile = self.store.get_post(post_id)
        if zeile is None or zeile["status"] != "draft":
            return {"ok": False, "grund": "Nur ein Entwurf lässt sich ändern."}
        draft = PostDraft.model_validate(json.loads(zeile["draft_json"]))
        if caption == draft.caption.strip():
            return {"ok": True, "unveraendert": True}
        draft.caption = caption
        self.store.setze_entwurfsdaten(post_id, draft)
        self._von_hand_geaendert(post_id)
        return {"ok": True}

    # --- Reel -------------------------------------------------------------

    def _reel_bilder(self, zeile) -> list[Path]:
        bilder = [Path(zeile["image_path"])] if zeile["image_path"] else []
        bilder += [Path(p) for p in json.loads(zeile["karussell_json"] or "[]")]
        return [b for b in bilder if b.is_file()]

    def reel_stand(self, post_id: int, zeile=None) -> dict:
        """Gibt es ein Reel, ist es auf dem Stand der Bilder, und soll es hinaus?"""
        from .imaging.reel import ist_aktuell, kann_reels

        zeile = zeile if zeile is not None else self.store.get_post(post_id)
        pfad = self.store.get_json(f"reel:{post_id}")
        pfad = Path(pfad) if pfad else None
        return {
            "datei": pfad.name if pfad and pfad.is_file() else None,
            "aktuell": bool(zeile) and ist_aktuell(pfad, self._reel_bilder(zeile)),
            "als_reel": self.store.get_json(f"format:{post_id}") == "reel",
            "moeglich": kann_reels(),
        }

    def reel_bauen(self, post_id: int) -> dict:
        """Baut das Reel aus den jetzigen Bildern - kostenlos, ohne KI."""
        from .imaging.reel import ReelFehler, baue_reel

        zeile = self.store.get_post(post_id)
        if zeile is None:
            return {"ok": False, "grund": "Diesen Beitrag gibt es nicht."}
        bilder = self._reel_bilder(zeile)
        if len(bilder) < 2:
            return {"ok": False, "grund": "Für ein Reel braucht es mindestens zwei Bilder."}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        ziel = self.settings.media_dir / f"{stamp}-reel-{post_id}.mp4"
        try:
            baue_reel(bilder, ziel)
        except ReelFehler as exc:
            return {"ok": False, "grund": str(exc)}
        alt = self.store.get_json(f"reel:{post_id}")
        self.store.set_json(f"reel:{post_id}", str(ziel))
        if alt and Path(alt) != ziel:
            Path(alt).unlink(missing_ok=True)  # das alte Video ist überholt
        return {"ok": True, "datei": ziel.name}

    def veroeffentlichen_als(self, post_id: int, als_reel: bool) -> dict:
        """Merkt sich, ob dieser Beitrag als Reel oder als Bilder hinausgeht."""
        zeile = self.store.get_post(post_id)
        if zeile is None or zeile["status"] not in ("draft", "approved"):
            return {"ok": False, "grund": "Das lässt sich nur vor dem Veröffentlichen wählen."}
        self.store.set_json(f"format:{post_id}", "reel" if als_reel else "bilder")
        return {"ok": True, "als_reel": als_reel}

    # --- Vorbilder ----------------------------------------------------------

    @property
    def vorbilder(self):
        from .models import Vorbilder

        roh = self.store.get_json(KEY_VORBILDER)
        try:
            return Vorbilder.model_validate(roh) if roh else None
        except Exception:  # noqa: BLE001 - ein alter Stand ist kein Grund zum Absturz
            return None

    def _sieh_vorbilder_an(self, identity, report: CycleReport, cycle: int | None = None):
        from .brain.vorbilder import beobachte_vorbilder

        try:
            vorbilder = beobachte_vorbilder(self.brain, identity=identity)
        except (BudgetExhausted, CycleBudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - ohne Vorbilder wird trotzdem geschrieben
            log.warning("Vorbilder nicht angesehen: %s", exc)
            report.steps.append(f"Vorbilder nicht angesehen: {exc}")
            return None
        self.store.set_json(KEY_VORBILDER, vorbilder)
        self.store.set_json(
            KEY_VORBILDER_ZYKLUS,
            cycle if cycle is not None else max(self.store.next_cycle_number() - 1, 0),
        )
        report.steps.append(
            f"Vorbilder angesehen: {len(vorbilder.accounts)} Accounts, "
            f"{len(vorbilder.fuer_uns)} Regeln für uns"
        )
        return vorbilder

    def vorbilder_neu(self) -> dict:
        """Auf Knopfdruck aus dem Dashboard: die Vorbilder jetzt neu ansehen."""
        identity = self.identity
        if identity is None:
            return {"ok": False, "grund": "Es gibt noch kein Profil."}
        self.treasury.check()
        lauf = CycleReport(started_at=datetime.now(timezone.utc))
        vorbilder = self._sieh_vorbilder_an(identity, lauf)
        if vorbilder is None:
            return {"ok": False, "grund": " ".join(lauf.steps) or "Das hat nicht geklappt."}
        return {"ok": True}

    def _von_hand_geaendert(self, post_id: int) -> None:
        """Merkt sich, dass die Prüfung die vorige Fassung betraf."""
        self.store.set_json(f"handgeaendert:{post_id}", True)
        self.store.log("text_von_hand", f"Entwurf {post_id}: Text von Hand geändert")

    def _karten_wiederfinden(self, post_id: int, draft, anzahl: int) -> bool:
        """Holt verlorene Kartentexte aus der Ablage der Entwürfe zurück.

        Vor dieser Korrektur gingen beim Nachbessern die Karten verloren:
        Die Bilder blieben, ihr Text im Entwurf war weg. Jeder Entwurf liegt
        aber auch als Datei in der Ablage, mit allen Rohdaten. Erkannt wird
        er am Bildprompt - den lässt das Nachbessern ausdrücklich stehen -
        und daran, dass er genau so viele Karten hat, wie es Bilder gibt.
        """
        for frueher in self.store.fruehere_fassungen(post_id):
            try:
                alt = PostDraft.model_validate(frueher)
            except Exception:  # noqa: BLE001
                continue
            if len(alt.karten) == anzahl:
                draft.karten = alt.karten
                self.store.setze_entwurfsdaten(post_id, draft)
                return True

        ordner = getattr(self.settings, "draft_dir", None)
        if not ordner or not Path(ordner).is_dir() or not draft.image_generation_prompt:
            return False
        for datei in sorted(Path(ordner).glob("*.md"), reverse=True):
            try:
                text = datei.read_text(encoding="utf-8")
                roh = text.split("```json", 1)[1].split("```", 1)[0]
                alt = PostDraft.model_validate(json.loads(roh))
            except Exception:  # noqa: BLE001 - diese Datei passt eben nicht
                continue
            if (
                alt.image_generation_prompt == draft.image_generation_prompt
                and len(alt.karten) == anzahl
            ):
                draft.karten = alt.karten
                self.store.setze_entwurfsdaten(post_id, draft)
                log.info("Karten von Entwurf %s aus %s wiedergefunden", post_id, datei.name)
                return True
        return False

    def bild_neu(self, post_id: int) -> dict:
        """Holt das Titelbild eines Entwurfs neu, ohne den Text anzufassen.

        Zuerst wird ein echtes Foto gesucht; nur wenn keines passt, wird
        gemalt. Gedacht fuer den Fall, dass einem das Bild nicht gefaellt.
        Die Bildsprache schreibt den Prompt vorher neu - ein zweiter Wurf
        mit demselben Prompt sieht meist fast gleich aus, und "gefaellt mir
        nicht" meint fast immer den Einfall, nicht den Zufall.

        Der Pruefbericht bleibt stehen: Er gilt fuer Zahlen und Quellen,
        und die haben sich nicht geaendert.
        """
        zeile = self.store.get_post(post_id)
        if zeile is None:
            return {"ok": False, "grund": "Diesen Entwurf gibt es nicht."}
        if zeile["status"] != "draft":
            return {"ok": False, "grund": "Nur bei einem Entwurf lässt sich das Bild tauschen."}

        identity = self.identity
        if identity is None:
            return {"ok": False, "grund": "Es gibt noch kein Profil."}

        draft = PostDraft.model_validate(json.loads(zeile["draft_json"]))
        lauf = CycleReport(started_at=datetime.now(timezone.utc))
        self.treasury.check()
        vorher = self.treasury.state().cycle_spent_usd

        fund = (
            Fund.model_validate(json.loads(zeile["fund_json"])) if zeile["fund_json"] else None
        )

        # Erst nach einem echten Foto suchen, dann erst die Bildsprache
        # fragen. Ihr Ergebnis ist ein neuer Malprompt - mit Websuche der
        # teuerste Teil von "Bild neu" -, und der ist umsonst bezahlt, wenn
        # am Ende ein Foto genommen wird. Die Suche wird aufgehoben, damit
        # sie beim Malen nicht ein zweites Mal läuft.
        # Nicht noch einmal dasselbe: Alles, was dieser Beitrag schon an
        # Bildern hatte, ist bei der Suche ausgeschlossen.
        self._ausschluss = self._abdruecke_des_beitrags(post_id, zeile)
        # Und das jetzige bleibt erreichbar: "vorheriges" holt es zurück.
        self._titel_in_verlauf(post_id, zeile, draft)

        gestaltung = None
        echtes_foto = False
        if fund is not None:
            self._bildprobe(fund, lauf)
            echtes_foto = self._bildproben[id(fund)].echt is not None
        if echtes_foto:
            lauf.steps.append("Bildsprache übersprungen - es gibt ein echtes Foto")
        else:
            gestaltung = self._gestalte(draft, identity, lauf)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        basis = f"{stamp}-neu-{post_id}"
        bild = render_post_image(
            draft.visual,
            self.settings.media_dir / f"{basis}.png",
            groesse=self._bildformat,
        )
        gemalt, rohbild = self._erzeuge_bild(draft, basis, identity, lauf, fund)
        if gemalt:
            bild = gemalt

        self.store.setze_bild(post_id, draft, str(bild))
        self.store.setze_rohbild(post_id, str(rohbild) if rohbild else None)
        self._merke_abdruecke(post_id, rohbild)
        self.store.setze_bildnachweis(post_id, getattr(self, "_letzter_nachweis", ""))
        if gestaltung is not None:
            self.store.set_gestaltung(post_id, gestaltung)
        kosten = self._mitrechnen(post_id, vorher)
        self.store.log(
            "bild_neu", f"Entwurf {post_id}: Bild neu gemalt ({kosten:.4f} USD)"
        )

        return {
            "ok": True,
            "gemalt": bool(gemalt),
            "niveau": gestaltung.niveau if gestaltung else None,
            "schritte": lauf.steps,
        }

    def _bessere_nach(self, post_id: int, bericht, report: CycleReport):
        """Lässt beanstandete Beiträge selbst nachbessern, begrenzt oft.

        Ohne das legt der Agent dem Betreiber Beiträge mit falschen Zahlen
        vor und überlässt ihm die Arbeit. Mit unbegrenzten Runden würde er
        sich an einem Thema festbeißen, das nicht trägt - deshalb die
        Grenze aus den Einstellungen.
        """
        for runde in range(max(self.settings.posting.nachbesserungen, 0)):
            if bericht is None or bericht.darf_raus:
                break
            try:
                self.treasury.check()
            except (BudgetExhausted, CycleBudgetExceeded) as exc:
                report.steps.append(f"Nachbessern ausgelassen: {exc}")
                break

            ergebnis = self.nachbessern(post_id)
            if not ergebnis.get("ok"):
                report.steps.append(f"Nachbessern nicht möglich: {ergebnis.get('grund')}")
                break

            report.steps.append(
                f"Entwurf {post_id} nachgebessert ({runde + 1}. Runde)"
                + (f", Endprüfung: {ergebnis['urteil']}" if ergebnis.get("urteil") else "")
            )
            zeile = self.store.get_post(post_id)
            bericht = (
                Pruefbericht.model_validate(json.loads(zeile["pruefung_json"]))
                if zeile and zeile["pruefung_json"]
                else None
            )

        if bericht is not None and not bericht.darf_raus:
            report.steps.append(
                f"Entwurf {post_id} bleibt beanstandet - das entscheidet ein Mensch"
            )
        return bericht

    def nachbessern(self, post_id: int) -> dict:
        """Schreibt einen beanstandeten Entwurf neu und prüft ihn erneut.

        Das ist der Weg, den es bisher nicht gab: Die Endprüfung fand
        Fehler, und der Entwurf blieb mit dem roten Vermerk liegen. Wer ihn
        freigab, veröffentlichte die falsche Zahl - eine Kontrolle, die
        etwas findet, aber nichts bewirkt, ist die schlechteste aller
        Möglichkeiten.

        Gibt zurück, was passiert ist. Der Entwurf wird an derselben Stelle
        ersetzt, mit neuem Bild und frischem Prüfbericht.
        """
        zeile = self.store.get_post(post_id)
        if zeile is None:
            return {"ok": False, "grund": "Diesen Entwurf gibt es nicht."}
        if zeile["status"] != "draft":
            return {"ok": False, "grund": "Nur ein Entwurf lässt sich nachbessern."}
        if not zeile["pruefung_json"]:
            return {"ok": False, "grund": "Ohne Prüfbericht gibt es nichts nachzubessern."}

        identity = self.identity
        if identity is None:
            return {"ok": False, "grund": "Es gibt noch kein Profil."}

        alt = PostDraft.model_validate(json.loads(zeile["draft_json"]))
        bericht = Pruefbericht.model_validate(json.loads(zeile["pruefung_json"]))
        if not bericht.beanstandet and bericht.darf_raus:
            return {"ok": False, "grund": "Hier hat die Endprüfung nichts beanstandet."}

        # Der Fund gehört mit: Nachgebessert wird der Text, nicht das
        # Thema. Ohne ihn würde die Nachbesserung womöglich bei etwas
        # anderem landen - und die Stoffsuche wäre umsonst bezahlt.
        fund = (
            Fund.model_validate(json.loads(zeile["fund_json"])) if zeile["fund_json"] else None
        )

        self.treasury.check()
        vorher = self.treasury.state().cycle_spent_usd
        neu = ueberarbeite_beitrag(
            self.brain,
            identity=identity,
            strategy=self.strategy,
            draft=alt,
            bericht=bericht,
            max_hashtags=self.settings.posting.max_hashtags,
            modell=self._modell("chef"),
            fund=fund,
            persona=self._persona_chef(),
        )
        if not neu.visual.footer.strip():
            neu.visual.footer = f"@{identity.handle}"

        # Das Motiv war nicht beanstandet, also bleibt es. Ein zweites Mal
        # zu malen hieße ein anderes Bild - und dann steht auf einmal ein
        # anderer Fisch über einem Text, der von etwas anderem handelt.
        # Wer das Motiv wechseln will, drückt "Bild neu".
        neu.image_generation_prompt = alt.image_generation_prompt

        bericht_lauf = CycleReport(started_at=datetime.now(timezone.utc))
        bild, wie = self._schrift_erneuern(zeile, neu, identity, post_id)
        bericht_lauf.steps.append(f"Bild: {wie}")

        # Der alte Entwurf kommt ins Protokoll. Ohne das war er weg, sobald
        # der neue gespeichert war - samt allem, was das Modell beim
        # Umschreiben verloren hatte.
        self.store.log(
            "nachbesserung",
            f"Entwurf {post_id}: Fassung vor dem Nachbessern",
            payload=alt.model_dump(mode="json"),
        )
        self.store.ersetze_entwurf(post_id, neu, str(bild))

        # Karten, deren Text sich geändert hat, brauchen ein neues Bild -
        # die alte Schrift steht fest darauf.
        bilder = json.loads(zeile["karussell_json"] or "[]")
        if fund is not None:
            self._bildthema = self._bildthema_fuer(fund)
        self._ausschluss = self._abdruecke_des_beitrags(post_id, zeile)
        self._benutzte_abdruecke = []
        for versatz, (vorige, jetzt) in enumerate(zip(alt.karten, neu.karten)):
            if versatz < len(bilder) and vorige.text.strip() != jetzt.text.strip():
                self._karte_erneuern(post_id, neu, bilder, versatz, identity, alte_karte=vorige)
                bericht_lauf.steps.append(f"Bild {versatz + 2}: neuer Text, neues Bild")
        self._merke_abdruecke(post_id)

        # Und noch einmal geprüft - sonst wäre die Nachbesserung nur eine
        # Behauptung. Aber als Nachprüfung gegen den ersten Bericht, ohne
        # neue Websuche: Die Belege liegen schon vor, geändert hat sich
        # eine Stelle. Die volle Prüfung ein zweites Mal kostete im
        # Goldrubel-Zyklus drei Minuten und einen guten Teil des Geldes.
        #
        # Reicht das Geld dafür nicht mehr, bleibt ein neu geschriebener
        # Entwurf ohne Bericht liegen. Der sieht dann aus wie einer, den
        # nie jemand geprüft hat - und das ist die gefährlichste aller
        # Anzeigen. Also wenigstens ins Protokoll damit.
        try:
            zweiter = self._pruefe_nach_dem_bessern(post_id, neu, identity, bericht, bericht_lauf, fund)
        except (BudgetExhausted, CycleBudgetExceeded):
            # Auch der abgebrochene Versuch hat Geld gekostet. Ihn nicht
            # mitzuzaehlen, wuerde den Beitrag billiger aussehen lassen,
            # als er war - und ausgerechnet der teure Fall faellt dann
            # unter den Tisch.
            self._mitrechnen(post_id, vorher)
            self.store.log(
                "nachbesserung",
                f"Entwurf {post_id} nachgebessert, aber nicht mehr geprüft - "
                "das Budget war aufgebraucht. Vor der Freigabe prüfen lassen.",
            )
            raise
        if zweiter is not None:
            self.store.set_json(f"handgeaendert:{post_id}", False)
        kosten = self._mitrechnen(post_id, vorher)
        self.store.log(
            "nachbesserung",
            f"Entwurf {post_id} nachgebessert"
            + (f", Endprüfung: {zweiter.urteil}" if zweiter else "")
            + f" ({kosten:.4f} USD)",
        )
        return {
            "ok": True,
            "urteil": zweiter.urteil if zweiter else None,
            "offen": len(zweiter.beanstandet) if zweiter else None,
            "bild": wie,
            "schritte": bericht_lauf.steps,
        }

    def pruefe_nach(self, post_id: int) -> dict:
        """Holt die Endprüfung für einen Entwurf nach, der keinen Bericht hat.

        Ein Entwurf ohne Bericht entsteht auf drei Wegen: Die Prüfung war
        abgeschaltet, sie ist an einem Netzfehler gescheitert, oder das
        Geld ging mitten in einer Nachbesserung aus - dann steht dort ein
        neu geschriebener Text, für den noch niemand nachgesehen hat.

        Alle drei sehen im Dashboard gleich aus: "nicht geprüft". Und
        solange es keinen Weg gibt, das nachzuholen, bleibt dem Betreiber
        nur freigeben oder wegwerfen. Das hier ist der dritte Weg.
        """
        zeile = self.store.get_post(post_id)
        if zeile is None:
            return {"ok": False, "grund": "Diesen Entwurf gibt es nicht."}
        if zeile["status"] != "draft":
            return {"ok": False, "grund": "Nur ein Entwurf lässt sich prüfen."}
        # Von Hand geänderter Text: Der Bericht galt der vorigen Fassung.
        # Dann wird nachgeprüft - gegen seine Belege, ohne neue Websuche.
        von_hand = bool(self.store.get_json(f"handgeaendert:{post_id}"))
        if zeile["pruefung_json"] and not von_hand:
            return {"ok": False, "grund": "Dieser Entwurf ist schon geprüft."}

        identity = self.identity
        if identity is None:
            return {"ok": False, "grund": "Es gibt noch kein Profil."}

        draft = PostDraft.model_validate(json.loads(zeile["draft_json"]))
        fund = (
            Fund.model_validate(json.loads(zeile["fund_json"])) if zeile["fund_json"] else None
        )
        lauf = CycleReport(started_at=datetime.now(timezone.utc))
        self.treasury.check()
        vorher = self.treasury.state().cycle_spent_usd

        erster = (
            Pruefbericht.model_validate(json.loads(zeile["pruefung_json"]))
            if zeile["pruefung_json"]
            else None
        )
        if von_hand and erster is not None and erster.mit_suche:
            bericht = pruefe_nachbesserung(
                self.brain,
                identity=identity,
                draft=draft,
                erster=erster,
                modell=self._modell("pruefung"),
                person=self._person("pruefung"),
                fund=fund,
            )
        else:
            # Absichtlich ohne die Abschaltung zu beachten: Wer hier drückt,
            # will geprüft haben, auch wenn die Prüfung sonst ausgeschaltet ist.
            bericht = pruefe_beitrag(
                self.brain,
                identity=identity,
                draft=draft,
                mit_suche=self.treasury.state().mode is Mode.NORMAL,
                modell=self._modell("pruefung"),
                person=self._person("pruefung"),
                fund=fund,
            )
        self.store.set_pruefung(post_id, bericht)
        self.store.set_json(f"handgeaendert:{post_id}", False)
        kosten = self._mitrechnen(post_id, vorher)
        self.store.log(
            "pruefung",
            f"Entwurf {post_id} nachträglich geprüft: {bericht.urteil} - "
            f"{bericht.zusammenfassung} ({kosten:.4f} USD)",
        )
        return {
            "ok": True,
            "urteil": bericht.urteil,
            "offen": len(bericht.beanstandet),
            "schritte": lauf.steps,
        }

    def _schrift_erneuern(self, zeile, neu: PostDraft, identity, post_id: int):
        """Setzt die Schrift neu auf dasselbe Grundbild - ohne neu zu malen.

        Drei Fälle, und keiner davon malt:

        - Der Text auf dem Bild ist derselbe geblieben. Dann bleibt auch
          das Bild, wie es war. Die falsche Zahl stand in der
          Bildunterschrift, nicht auf dem Bild.
        - Der Text hat sich geändert und es gibt ein Grundbild. Dann
          bekommt dasselbe Motiv die neue Schrift.
        - Es gibt kein Grundbild, weil es bei der Typografie blieb. Dann
          wird die typografische Fassung neu gesetzt, und die kostet
          nichts.

        Gibt den Bildpfad zurück und in einem Wort, was passiert ist.
        """
        altes_bild = Path(zeile["image_path"]) if zeile["image_path"] else None
        rohbild = Path(zeile["rohbild_path"]) if zeile["rohbild_path"] else None
        if rohbild is None and altes_bild and altes_bild.name.endswith("-fertig.png"):
            # Entwürfe von vor dieser Änderung kennen die Spalte noch nicht.
            # Das Grundbild liegt aber seit jeher daneben, unter demselben
            # Namen mit "-roh" statt "-fertig".
            nachbar = altes_bild.with_name(altes_bild.name.replace("-fertig.png", "-roh.png"))
            if nachbar.is_file():
                rohbild = nachbar
        alter_text = PostDraft.model_validate(json.loads(zeile["draft_json"])).bildtext

        if altes_bild and altes_bild.is_file() and neu.bildtext.strip() == alter_text.strip():
            return altes_bild, "unverändert"

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        basis = f"{stamp}-nachgebessert-{post_id}"

        if rohbild and rohbild.is_file():
            try:
                neues = lege_hook_auf(
                    rohbild,
                    self.settings.media_dir / f"{basis}-fertig.png",
                    text=neu.bildtext,
                    spec=neu.visual,
                    handle=f"@{identity.handle}",
                    groesse=self._bildformat,
                )
                return neues, "neu beschriftet"
            except Exception as exc:  # noqa: BLE001 - dann eben die Typografie
                log.warning("Schrift liess sich nicht neu auflegen: %s", exc)

        typo = render_post_image(
            neu.visual,
            self.settings.media_dir / f"{basis}.png",
            groesse=self._bildformat,
        )
        return typo, "typografisch neu gesetzt"

    def bildsprache_erneuern(self):
        """Lässt den Agenten seine Bildsprache neu schreiben und übernimmt sie.

        Gibt das Ergebnis zurück, oder None, wenn es noch keine Identität
        gibt. Der Rest der Identität bleibt unangetastet - es ist eine
        Korrektur, kein Neuanfang.
        """
        identity = self.identity
        if identity is None:
            return None

        neu = erneuere_bildsprache(self.brain, identity)
        vorher = identity.visual_identity
        identity.visual_identity = neu.visual_identity
        self.store.set_json(KEY_IDENTITY, identity)
        self.store.log(
            "identity",
            f"Bildsprache neu festgelegt: {neu.was_sich_aendert}",
            payload={"vorher": vorher, "nachher": neu.visual_identity},
        )
        log.info("Bildsprache erneuert: %s", neu.was_sich_aendert)
        return neu

    @property
    def modellwahl(self) -> dict:
        """Welches Modell der Betreiber welcher Rolle zugewiesen hat."""
        from .mannschaft import KEY_MODELLWAHL

        return self.store.get_json(KEY_MODELLWAHL) or {}

    def _modell(self, schluessel: str) -> str | None:
        """Das gewählte Modell einer Rolle, oder None für die Voreinstellung."""
        return self.modellwahl.get(schluessel)

    @property
    def mannschaft(self) -> dict:
        """Was der Betreiber an den Steckbriefen geändert hat."""
        from .mannschaft import KEY_MANNSCHAFT

        return self.store.get_json(KEY_MANNSCHAFT) or {}

    def _person(self, schluessel: str) -> dict:
        """Name, Haltung und Aussehen einer Rolle, nach den Änderungen."""
        from .mannschaft import person

        return person(schluessel, self.mannschaft, self.identity)

    def _persona_chef(self) -> str:
        """Die Haltung des Chefs, um die Vorgabe des Betreibers ergänzt.

        Sie wirkt dort, wo sie sich zeigt: beim Schreiben und beim
        Nachbessern. Für das Ordnen von Zahlen ändert ein Charakterzug
        nichts, und dort wäre er nur bezahlte Länge im Prompt.
        """
        from .brain.prompts import persona_chef

        return persona_chef(self._person("chef").get("haltung", ""))

    def aendere_person(self, schluessel: str, felder: dict) -> dict:
        """Schreibt den Steckbrief einer Rolle um.

        Beim Chef wandern Name und Aufgabe in die Identität und nicht in
        die Anpassung: Unter diesem Namen schreibt er, mit diesem Motto
        arbeitet er. Zwei Wahrheiten nebeneinander wären eine zu viel.
        """
        from .mannschaft import FELDER, KEY_MANNSCHAFT, NACH_SCHLUESSEL, person

        if schluessel not in NACH_SCHLUESSEL:
            return {"ok": False, "grund": "Diese Rolle gibt es nicht."}

        sauber = {
            f: (
                [str(x).strip() for x in felder[f] if str(x).strip()][:5]
                if f == "eigenschaften"
                else str(felder[f]).strip()
            )
            for f in FELDER
            if f in felder and felder[f] is not None
        }
        # Beim Chef zählen die Profilfelder mit: Wer nur die Nische
        # umschreibt, hat sehr wohl etwas geändert.
        profil = schluessel == "chef" and any(f in felder for f in PROFILFELDER)
        if not sauber and not profil:
            return {"ok": False, "grund": "Es gab nichts zu ändern."}

        if schluessel == "chef":
            identity = self.identity
            if identity is None:
                return {"ok": False, "grund": "Es gibt noch kein Profil."}
            if name := sauber.pop("name", ""):
                identity.agent_name = name
            if motto := sauber.pop("aufgabe", ""):
                identity.motto = motto
            # Der Rest des Profils gehört ebenso dem Betreiber. Es steht
            # jetzt fest im Quelltext, statt erfunden zu werden - dann
            # muss es sich aber auch ohne Quelltext ändern lassen.
            for feld in PROFILFELDER:
                wert = felder.get(feld)
                if feld == "content_pillars":
                    if isinstance(wert, list) and (
                        saeulen := [str(x).strip() for x in wert if str(x).strip()][:5]
                    ):
                        if len(saeulen) >= 3:
                            identity.content_pillars = saeulen
                elif isinstance(wert, str) and wert.strip():
                    setattr(identity, feld, wert.strip())
            self.store.set_json(KEY_IDENTITY, identity)

        alle = self.mannschaft
        alle[schluessel] = {**(alle.get(schluessel) or {}), **sauber}
        self.store.set_json(KEY_MANNSCHAFT, alle)

        jetzt = person(schluessel, alle, self.identity)
        self.store.log("mannschaft", f"{jetzt['name']}: Steckbrief geändert")
        return {"ok": True, "person": jetzt}

    def male_portrait_neu(self, schluessel: str) -> dict:
        """Malt das Porträt einer Person neu - auch wenn schon eines da ist.

        Nötig, weil das Bildmodell nichts über die Person weiß. Es malt,
        was im Bildwunsch steht, und trifft dabei weder Alter noch
        Aussehen noch sonst etwas verlässlich. Wer damit leben muss, darf
        es bestimmen.
        """
        from .imaging.portraits import male_portrait, portraitpfad
        from .mannschaft import NACH_SCHLUESSEL

        rolle = NACH_SCHLUESSEL.get(schluessel)
        if rolle is None:
            return {"ok": False, "grund": "Diese Rolle gibt es nicht."}
        if self.bildgenerator is None:
            return {"ok": False, "grund": "Kein Bilddienst eingerichtet."}

        eigen = self._person(schluessel)
        ziel = portraitpfad(self.settings.media_dir, schluessel)
        pfad, grund = male_portrait(
            self.bildgenerator, rolle, ziel, self.identity, eigen.get("bildwunsch", "")
        )
        if pfad is None:
            return {"ok": False, "grund": grund or "Das hat nicht geklappt."}
        self.store.log("mannschaft", f"{eigen['name']}: Porträt neu gemalt")
        return {"ok": True}

    def _pruefe(self, post_id: int, draft, identity, report: CycleReport, fund=None):
        """Lässt die Endprüfung über den Entwurf gehen.

        Gibt den Bericht zurück, oder None, wenn nicht geprüft werden
        konnte. Ein Fehlschlag hier darf den Zyklus nicht kosten - aber er
        darf auch nicht als "geprüft" durchgehen. Deshalb None und ein
        sichtbarer Vermerk statt eines stillen Weiter.
        """
        if not self.settings.posting.pruefung_noetig:
            return None
        try:
            bericht = pruefe_beitrag(
                self.brain,
                identity=identity,
                draft=draft,
                # Ohne Websuche lässt sich keine Quelle nachschlagen. Geprüft
                # wird trotzdem - Rechenfehler fallen auch so auf.
                mit_suche=self.treasury.state().mode is Mode.NORMAL,
                modell=self._modell("pruefung"),
                person=self._person("pruefung"),
                # Der Fund gehört mit: Erfunden wird nicht im Text,
                # sondern beim Suchen. Eine erfundene Art klingt genau
                # wie eine echte.
                fund=fund,
            )
        except (BudgetExhausted, CycleBudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - der Grund gehört ins Protokoll
            log.warning("Endprüfung fehlgeschlagen: %s", exc)
            report.steps.append(f"Entwurf {post_id} konnte nicht geprüft werden: {exc}")
            self.store.log("pruefung_error", f"Entwurf {post_id}: {exc}")
            return None

        self.store.set_pruefung(post_id, bericht)
        beanstandet = len(bericht.beanstandet)
        report.steps.append(
            f"Endprüfung {post_id}: {bericht.urteil}"
            + (f", {beanstandet} beanstandet" if beanstandet else "")
        )
        self.store.log(
            "pruefung",
            f"Entwurf {post_id}: {bericht.urteil} - {bericht.zusammenfassung}",
        )
        return bericht

    def _pruefe_nach_dem_bessern(
        self, post_id: int, draft, identity, erster, report: CycleReport, fund=None
    ):
        """Die Nachprüfung nach dem Nachbessern - gegen den ersten Bericht.

        Hatte die erste Prüfung keine Websuche, gibt es nichts, wogegen sich
        vergleichen ließe; dann läuft die volle Prüfung.
        """
        if not self.settings.posting.pruefung_noetig:
            return None
        if not erster.mit_suche:
            return self._pruefe(post_id, draft, identity, report, fund)
        try:
            bericht = pruefe_nachbesserung(
                self.brain,
                identity=identity,
                draft=draft,
                erster=erster,
                modell=self._modell("pruefung"),
                person=self._person("pruefung"),
                fund=fund,
            )
        except (BudgetExhausted, CycleBudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - der Grund gehört ins Protokoll
            log.warning("Nachprüfung fehlgeschlagen: %s", exc)
            report.steps.append(f"Entwurf {post_id} konnte nicht nachgeprüft werden: {exc}")
            self.store.log("pruefung_error", f"Entwurf {post_id}: {exc}")
            return None

        self.store.set_pruefung(post_id, bericht)
        beanstandet = len(bericht.beanstandet)
        report.steps.append(
            f"Nachprüfung {post_id}: {bericht.urteil}"
            + (f", {beanstandet} beanstandet" if beanstandet else "")
        )
        self.store.log(
            "pruefung",
            f"Entwurf {post_id} nachgeprüft: {bericht.urteil} - {bericht.zusammenfassung}",
        )
        return bericht

    def _suche_stoff(self, report: CycleReport) -> Fund | None:
        """Sucht den Fund, auf dem der nächste Beitrag steht.

        Gibt None zurück, wenn die Stoffsuche abgeschaltet ist oder
        scheitert. Dann schreibt der Agent selbst ein Thema - schwächer,
        aber besser als ein Zyklus ohne Beitrag.

        Ist der Fund zu schwach, wird genau einmal nachgesetzt. Jede
        weitere Runde kostet so viel wie die erste, und wer zweimal nichts
        findet, findet auch beim dritten Mal nichts. Bei knapper Kasse
        entfällt der zweite Anlauf.
        """
        if not self.settings.posting.stoff_noetig:
            return None

        bisherige = self.store.letzte_funde(limit=12)
        gebiete = self.store.letzte_gebiete(limit=6)
        mit_suche = self.treasury.state().mode is Mode.NORMAL
        fund = None
        try:
            fund = finde_stoff(
                self.brain,
                identity=self.identity,
                strategy=self.strategy,
                bisherige=bisherige,
                gebiete=gebiete,
                mit_suche=mit_suche,
                modell=self._modell("stoff"),
                person=self._person("stoff"),
            )
            if not fund.taugt and mit_suche:
                report.steps.append(
                    f"Stoff zu schwach (Reiz {fund.reiz}/5): {fund.titel} - noch einmal gesucht"
                )
                zweiter = finde_stoff(
                    self.brain,
                    identity=self.identity,
                    strategy=self.strategy,
                    bisherige=bisherige,
                    gebiete=gebiete,
                    mit_suche=mit_suche,
                    modell=self._modell("stoff"),
                    nachsetzen=fund,
                    person=self._person("stoff"),
                )
                # Der bessere von beiden, nicht einfach der zweite: Auch
                # der Nachschlag kann schwächer ausfallen.
                if zweiter.reiz >= fund.reiz:
                    fund = zweiter
                nachgesetzt = True
            else:
                nachgesetzt = False

            # Laesst sich die Sache zeigen? Instagram ist ein Bildmedium,
            # und ein Fund ohne freies Foto wird ein Beitrag aus fremden
            # Bildern. Einmal wird nachgesetzt - aber nicht zusaetzlich zu
            # einem Nachschlag wegen zu wenig Reiz: Jede Runde kostet so
            # viel wie die erste.
            if not self._bildprobe(fund, report) and mit_suche and not nachgesetzt:
                report.steps.append(
                    f"Kein freies Foto, das die Sache zeigt: {fund.titel} "
                    "- noch einmal gesucht"
                )
                zweiter = finde_stoff(
                    self.brain,
                    identity=self.identity,
                    strategy=self.strategy,
                    bisherige=bisherige,
                    gebiete=gebiete,
                    mit_suche=mit_suche,
                    modell=self._modell("stoff"),
                    nachsetzen=fund,
                    person=self._person("stoff"),
                    grund=(
                        "Von dieser Sache ließ sich kein frei nutzbares Foto "
                        "finden, das sie selbst zeigt - weder in der Studie "
                        "noch bei einer Behörde noch im Archiv. Instagram ist "
                        "ein Bildmedium; ein Beitrag aus fremden Bildern wirkt "
                        "zusammengewürfelt. Such einen Fund, von dem es ein "
                        "freies Foto gibt, und nenn seine Quelle."
                    ),
                )
                if self._bildprobe(zweiter, report) and zweiter.taugt:
                    fund = zweiter
                else:
                    report.steps.append(
                        "Auch beim zweiten Fund kein besseres Foto - "
                        "es bleibt beim ersten"
                    )
        except (BudgetExhausted, CycleBudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - der Grund gehört ins Protokoll
            log.warning("Stoffsuche fehlgeschlagen: %s", exc)
            report.steps.append(f"Stoffsuche fehlgeschlagen: {exc}")
            self.store.log("stoff_error", str(exc))
            return fund

        report.steps.append(
            f"Stoff: {fund.titel} (Reiz {fund.reiz}/5, {fund.beleglage})"
        )
        self.store.log(
            "stoff",
            f"{fund.titel} - Reiz {fund.reiz}/5, {fund.beleglage}"
            + (f", verworfen: {len(fund.verworfen)}" if fund.verworfen else ""),
        )
        if not fund.taugt:
            # Der Beitrag entsteht trotzdem, aber im Protokoll steht, dass
            # er auf schwachem Stoff steht. Ein Zyklus ohne Beitrag wäre
            # teurer als ein mittelmäßiger Beitrag.
            report.steps.append(
                f"Achtung: bester Fund nur Reiz {fund.reiz}/5 - der Beitrag trägt womöglich nicht"
            )
        return fund

    def _bildprobe(self, fund, report: CycleReport) -> bool:
        """Sucht das Bild zum Fund schon jetzt - True, wenn es die Sache zeigt.

        Frueher kam das Bild erst nach dem Text. Bei der leuchtenden
        Koralle hiess das: Stoffsuche, Text, Bildsprache waren bezahlt,
        als sich herausstellte, dass es von dieser Art kein freies Foto
        gibt - und der Beitrag bekam einen Frosch, eine Treppe und einen
        Krill. Jetzt wird zuerst geschaut, ob sich die Sache zeigen laesst.

        Das Ergebnis wird aufgehoben und spaeter verwendet; gesucht wird
        also nicht doppelt, und die Bildfragen kosten dasselbe wie vorher.

        "Zeigt die Sache" heisst: ein Bild aus der Originalquelle, oder
        ein Archivbild, das beim Hinsehen mindestens 7 von 10 bekam - "eine
        echte Aufnahme von etwas, das eng dazugehoert". Ist Hinsehen
        abgeschaltet, gilt jedes gefundene Foto; beurteilen laesst es sich
        dann nicht.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        basis = f"{stamp}-stoff-{len(getattr(self, '_bildproben', {})) + 1}"
        echt, nachweis = self._echtes_bild(fund, basis, report)
        stufe = getattr(self, "_letzte_bildstufe", None)

        if not hasattr(self, "_bildproben"):
            self._bildproben = {}
        self._bildproben[id(fund)] = Bildprobe(
            echt=echt,
            nachweis=nachweis,
            quellbilder=list(getattr(self, "_quellbilder", []) or []),
            bildthema=getattr(self, "_bildthema", ""),
            stufe=stufe,
        )
        return self._bildproben[id(fund)].zeigt_die_sache

    def _gestalte(self, draft, identity, report: CycleReport):
        """Lässt die Bildsprache über den geplanten Beitrag sehen.

        Der überarbeitete Prompt wird wirklich übernommen - sonst wäre das
        Urteil nur eine Meinung im Protokoll. Der ursprüngliche Prompt
        bleibt im Bericht stehen, damit nachvollziehbar ist, was sich
        geändert hat.
        """
        if not self.settings.posting.gestaltung_noetig:
            return None
        if getattr(self, "_bilder_heute_aus", None):
            # Ihr Ergebnis ist ein ueberarbeiteter Bildprompt. Ohne Bild
            # waere das bezahlte Arbeit fuer nichts.
            report.steps.append("Bildsprache uebersprungen - heute wird nicht mehr gemalt")
            return None
        try:
            urteil = pruefe_gestaltung(
                self.brain,
                identity=identity,
                draft=draft,
                mit_suche=self.treasury.state().mode is Mode.NORMAL,
                modell=self._modell("bildsprache"),
                person=self._person("bildsprache"),
            )
        except (BudgetExhausted, CycleBudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - der Grund gehört ins Protokoll
            log.warning("Bildsprache fehlgeschlagen: %s", exc)
            report.steps.append(f"Bildsprache konnte nicht sehen: {exc}")
            return None

        if neuer := urteil.bildprompt.strip():
            draft.image_generation_prompt = neuer

        report.steps.append(
            f"Bildsprache: Niveau {urteil.niveau}/5"
            + (", Prompt überarbeitet" if urteil.bildprompt.strip() else "")
        )
        self.store.log("gestaltung", f"Niveau {urteil.niveau}/5 - {urteil.urteil}")
        return urteil

    def _echtes_bild(self, fund, basis: str, report: CycleReport) -> tuple[Path | None, str]:
        """Sucht eine echte Aufnahme des Fundes in einem freien Bildarchiv.

        Ein gemaltes Bild zeigt, wie etwas aussehen könnte. Bei einem Fund
        ist das die zweitbeste Lösung: Wer liest, dass 140 Münzen 1.800
        Jahre unberührt lagen, will die Münzen sehen.

        Gibt den Pfad und die Pflichtangabe zurück, oder zweimal nichts -
        dann wird gemalt. Genommen wird nur, was ausdrücklich auch
        gewerblich genutzt und bearbeitet werden darf; auf jedes Bild
        kommt schliesslich Schrift.
        """
        from .imaging.echtbild import finde_und_hole, suchworte_fuer

        # Worum es auf allen Bildern gehen muss - auch auf den Karten. Ohne
        # das wurde jedes Kartenbild gegen sein eigenes Suchwort beurteilt,
        # und eine Treppe in einer Hoehle passte bestens zu "cave".
        self._bildthema = self._bildthema_fuer(fund)

        # Die Aufnahmen vom Fund selbst zuerst - aus der Studie, von der
        # Behoerde. Ein Archivbild passt zum Thema; dieses zeigt die Sache.
        self._quellbilder = []
        self._letzte_bildstufe = None
        aus_quelle = self._bild_aus_der_quelle(fund, basis, report)
        if aus_quelle is not None:
            return aus_quelle

        worte = suchworte_fuer(fund)
        if not worte:
            return None, ""

        # Mehrere Anlaeufe, vom Genauesten zum Allgemeinsten. Solange die
        # Bilderzeugung liefert, was sie liefert, ist jede echte Aufnahme
        # den zusaetzlichen Versuch wert - ein gemaltes Bild zeigt nur,
        # wie etwas aussehen koennte.
        ziel = self.settings.media_dir / f"{basis}-echt.jpg"
        gefunden = None
        for suchwort in worte:
            try:
                gefunden = finde_und_hole(
                    suchwort,
                    ziel,
                    groesse=self._bildformat,
                    # Gegen den Fund beurteilt, nicht gegen das Suchwort.
                    # Der letzte Anlauf sucht das Themenfeld - "archaeological
                    # excavation site" -, und eine Grabung auf Kreta passte
                    # dazu mit 7 von 10. Zum Muenzschatz in Russland passt
                    # sie nicht.
                    blick=self._blick_auf(getattr(self, "_bildthema", "") or suchwort),
                )
            except Exception as exc:  # noqa: BLE001 - ohne Foto wird gemalt
                log.info("Bildsuche fehlgeschlagen (%r): %s", suchwort, exc)
                gefunden = None
            if gefunden is not None:
                break

        if gefunden is None:
            report.steps.append(
                f"Keine freie Aufnahme zu {', '.join(repr(w) for w in worte)} "
                "- es wird gemalt"
            )
            return None, ""

        report.steps.append(
            f"Echte Aufnahme übernommen: {gefunden.seite} ({gefunden.lizenz})"
            + (f" - {gesehen}" if (gesehen := getattr(gefunden, "gesehen", "")) else "")
        )
        self.store.log("bild_echt", f"{gefunden.seite} - {gefunden.lizenz}")
        self._letzte_bildstufe = _blickpunkte(gesehen)
        return gefunden.pfad, gefunden.nachweis

    def _bild_aus_der_quelle(self, fund, basis: str, report: CycleReport):
        """Ein Bild vom Fund selbst, aus der Originalquelle - oder None.

        Die Stoffsuche nennt die Studie oder die Behoerde, von der der Fund
        stammt. Ist das eine freie Quelle - offene Fachzeitschrift unter
        CC BY, US-Behoerde -, stehen dort die Aufnahmen, um die es geht:
        der Schatz, der Fundort, das neue Tier. Genau die will jemand
        sehen, der von dem Fund liest.

        Die uebrigen brauchbaren Bilder derselben Seite landen in
        `self._quellbilder` und fuellen danach das Karussell - vor jedem
        Archivbild, das nur zum Thema passt.
        """
        from .imaging.europepmc import doi_des_fundes
        from .imaging.quellbild import aus_der_quelle, aus_der_studie, quellseiten

        doi = doi_des_fundes(fund)
        seiten = quellseiten(fund)
        if not doi and not seiten:
            return None

        # Worueber das Bild sein soll: der englische Suchbegriff und der
        # Titel des Fundes. Beides zusammen sagt dem Blick genauer als
        # jedes allein, was zu sehen sein muesste.
        thema = " - ".join(
            teil
            for teil in (getattr(fund, "bildsuche", ""), getattr(fund, "titel", ""))
            if teil
        )
        ziel = self.settings.media_dir / f"{basis}-echt.jpg"
        befunde: list = []
        blick = self._blick_auf(thema)
        gefunden = None

        # Zuerst ueber Europe PMC: Viele Verlage sperren Programme aus -
        # beim ersten echten Versuch antwortete die Royal Society mit 403,
        # obwohl die Studie frei war. Das Archiv ist fuer solche Abrufe da.
        if doi:
            try:
                gefunden = aus_der_studie(
                    doi,
                    ziel,
                    groesse=self._bildformat,
                    blick=blick,
                    weitere=self._quellbilder,
                    befunde=befunde,
                )
            except Exception as exc:  # noqa: BLE001 - dann die Verlagsseite
                log.info("Bild aus der Studie fehlgeschlagen: %s", exc)

        if gefunden is None and seiten:
            try:
                gefunden = aus_der_quelle(
                    seiten,
                    ziel,
                    groesse=self._bildformat,
                    blick=blick,
                    weitere=self._quellbilder,
                    befunde=befunde,
                )
            except Exception as exc:  # noqa: BLE001 - dann eben das Archiv
                log.info("Bild aus der Quelle fehlgeschlagen: %s", exc)

        if gefunden is None:
            gruende = "; ".join(
                f"{b.quelle.name if b.quelle else b.seite}: {b.grund}"
                for b in befunde
                if b.grund
            )
            report.steps.append(
                "Kein freies Bild in der Originalquelle"
                + (f" ({gruende})" if gruende else "")
                + " - es wird im Archiv gesucht"
            )
            return None

        dazu = (
            f", dazu {len(self._quellbilder)} weitere fürs Karussell"
            if self._quellbilder
            else ""
        )
        report.steps.append(
            f"Aufnahme vom Fund selbst übernommen: {gefunden.seite} "
            f"({gefunden.lizenz}){dazu}"
        )
        self.store.log("bild_quelle", f"{gefunden.seite} - {gefunden.lizenz}")
        self._letzte_bildstufe = BILD_VOM_FUND
        return gefunden.pfad, gefunden.nachweis

    def _panorama_karussell(self, draft, basis: str, identity, erstes_roh):
        """Aus einer sehr breiten Aufnahme ein Karussell zum Durchwandern.

        Gibt das beschriftete erste Stueck und die uebrigen zurueck, oder
        zweimal nichts, wenn das Bild dafuer nicht taugt - dann bleibt es
        beim gewoehnlichen Karussell aus Faktenkarten.

        Das erste Stueck ersetzt das Hauptbild des Beitrags: Im Feed steht
        dann der linke Rand der Aufnahme, und alles Weitere liegt rechts
        davon.

        Beschriftet wird nur das erste Stueck. Eine Zeile auf jedem Teil
        zerhackt die Aufnahme und nimmt ihr genau das, wofuer man sie
        genommen hat; die Fakten stehen dann in der Bildunterschrift.
        """
        if erstes_roh is None or not Path(erstes_roh).exists():
            return None, []

        from .imaging.panorama import ist_panorama, zerschneide

        if not ist_panorama(Path(erstes_roh)):
            return None, []

        breite, hoehe = self._bildformat
        stuecke = zerschneide(
            Path(erstes_roh),
            self.settings.media_dir / basis,
            format_breite=breite,
            format_hoehe=hoehe,
        )
        if len(stuecke) < 2:
            return None, []

        # Nur das erste Stueck bekommt den Hook - es ist das, was im Feed
        # steht. Die uebrigen bleiben unberuehrt, damit die Aufnahme
        # durchlaeuft.
        erstes = self.settings.media_dir / f"{basis}-fertig.png"
        try:
            lege_hook_auf(
                stuecke[0],
                erstes,
                text=draft.bildtext,
                spec=draft.visual,
                handle=f"@{identity.handle}",
                groesse=self._bildformat,
            )
        except Exception as exc:  # noqa: BLE001 - dann eben ohne Schrift
            log.warning("Schrift auf Panoramastueck fehlgeschlagen: %s", exc)
            erstes = stuecke[0]

        return erstes, stuecke[1:]

    @property
    def _bildformat(self) -> tuple[int, int]:
        """Das Format, in dem dieser Beitrag erscheint - FEED oder STORY.

        Es an einer Stelle zu holen ist kein Aufraeumen, sondern der Kern
        eines Fehlers: Das Format stand zwar in den Einstellungen, wurde
        beim Beschriften der Bilder aber nie gelesen. Jedes Bild landete
        auf 9:16, auch bei einem Feed-Beitrag - und wurde dafuer
        hochgerechnet, statt herunter. Genau daher kam die Unschaerfe.
        """
        # Ueber getattr, aus demselben Grund wie beim Hinsehen: Der
        # Ausdruck steht mitten im Aufruf der Bildsuche, und der faengt
        # jeden Fehler als "nichts gefunden" ab. FEED ist ohnehin die
        # Voreinstellung - Instagram nimmt im Feed nur 4:5 bis 1.91:1 an.
        posting = getattr(self.settings, "posting", None)
        return STORY if getattr(posting, "bildformat", "feed") == "story" else FEED

    def _blick_auf(self, thema: str):
        """Die Stelle, an der jemand hinsieht - oder None, wenn niemand soll.

        Ein Thema muss dastehen: Ohne das wuesste das Modell nicht, wozu
        das Bild passen soll, und eine Frage ohne Vergleichsmassstab
        kostet Geld und bringt nichts.
        """
        hinsehen = Agent._nur_hinsehen(self, thema)
        ausschluss = list(getattr(self, "_ausschluss", None) or [])
        if not ausschluss:
            return hinsehen

        from .imaging.abdruck import schon_verwendet
        from .imaging.blick import UNGEPRUEFT

        # Vor dem Hinsehen, weil es nichts kostet: Ist es ein Bild, das
        # dieser Beitrag schon hat oder hatte, fliegt es gleich raus.
        def mit_ausschluss(pfad, herkunft=""):
            if schon_verwendet(pfad, ausschluss):
                return 0, "schon in diesem Beitrag verwendet"
            return hinsehen(pfad, herkunft) if hinsehen else (UNGEPRUEFT, "")

        return mit_ausschluss

    def _nur_hinsehen(self, thema: str):
        thema = (thema or "").strip()
        if not thema:
            return None

        # Nichts hier darf werfen, und das ist keine Vorsicht, sondern
        # eine Lehre: Diese Funktion wird mitten im Aufruf der Bildsuche
        # ausgewertet, und der steht in einem try, das jeden Fehler als
        # "nichts gefunden" auslegt. Ein fehlendes Feld haette damit
        # nicht das Hinsehen abgeschaltet, sondern die ganze Bildsuche -
        # lautlos, und der Beitrag haette wieder ein gemaltes Bild.
        posting = getattr(self.settings, "posting", None)
        if not getattr(posting, "bilder_ansehen", False):
            return None
        if getattr(self, "_bilder_heute_aus", ""):
            return None
        gehirn = getattr(self, "brain", None)
        if gehirn is None:
            return None

        def hinsehen(pfad, herkunft=""):
            return gehirn.beurteile_bild(pfad, thema, herkunft)

        return hinsehen

    def _merke_fuer_beitrag(self, pfad) -> None:
        """Merkt sich den Abdruck eines genommenen Fotos, bis der Beitrag feststeht."""
        from .imaging.abdruck import abdruck

        if (wert := abdruck(pfad)) is not None:
            if not isinstance(getattr(self, "_benutzte_abdruecke", None), list):
                self._benutzte_abdruecke = []
            self._benutzte_abdruecke.append(wert)

    def _karte_rohbild(self, karte, basis: str, nummer: int):
        """Das nackte Bild einer Karte - echt oder gemalt, noch ohne Schrift.

        Getrennt von der Beschriftung, und das ist der Punkt: Angeglichen
        wird die ganze Reihe auf einmal, und das geht nur, solange noch
        keine Schrift darauf liegt. Sonst wuerde die Helligkeitskorrektur
        den Text mit verschieben.
        """
        stamm = f"{basis}-k{nummer}"

        # Weitere Aufnahmen vom Fund selbst gehen vor jeder Suche. Sie
        # stammen aus derselben Studie wie das erste Bild und zeigen
        # dieselbe Sache - ein Archivbild passt nur zum Thema.
        rest = getattr(self, "_quellbilder", None)
        while rest:
            bild = rest.pop(
                _passendstes_bild(
                    rest, getattr(karte, "text", ""), getattr(self, "_bildthema", "")
                )
            )
            if bild.pfad is not None and Path(bild.pfad).exists():
                from .imaging.abdruck import schon_verwendet

                if schon_verwendet(bild.pfad, getattr(self, "_ausschluss", None)):
                    continue
                self._merke_fuer_beitrag(bild.pfad)
                return bild.pfad, bild.nachweis

        # Eine echte Aufnahme schlaegt jedes gemalte Bild - wenn sie die
        # Sache des Beitrags zeigt. Beurteilt wird deshalb gegen den Fund,
        # nicht gegen das Suchwort der Karte, und mit hoeherer Latte.
        if suchwort := (karte.bildsuche or "").strip():
            from .imaging.echtbild import KARTENBLICK, finde_und_hole

            thema = getattr(self, "_bildthema", "") or suchwort
            ziel = self.settings.media_dir / f"{stamm}-echt.jpg"
            try:
                gefunden = finde_und_hole(
                    suchwort,
                    ziel,
                    groesse=self._bildformat,
                    blick=self._blick_auf(thema),
                    mindestblick=KARTENBLICK,
                )
            except Exception as exc:  # noqa: BLE001 - dann wird gemalt
                log.info("Kartensuche fehlgeschlagen: %s", exc)
                gefunden = None
            if gefunden is not None and gefunden.pfad is not None:
                self._merke_fuer_beitrag(gefunden.pfad)
                return gefunden.pfad, gefunden.nachweis

        # Sonst gemalt, mit dem Prompt dieser Karte.
        wunsch = (karte.bildwunsch or "").strip()
        if self.bildgenerator is not None and wunsch and not self._bilder_heute_aus:
            ziel = self.settings.media_dir / f"{stamm}-roh.png"
            try:
                self.bildgenerator.erzeuge(wunsch, ziel)
                return ziel, ""
            except KontingentErschoepft as exc:
                self._bilder_heute_aus = str(exc)
                log.warning("Karte %s nicht gemalt: %s", nummer, exc)
            except Exception as exc:  # noqa: BLE001 - dann typografisch
                log.warning("Karte %s nicht gemalt: %s", nummer, exc)

        return None, ""

    def _beschrifte_karte(self, karte, roh, basis: str, nummer: int, draft, identity):
        """Die Schrift auf eine Karte - oder die typografische Fassung.

        Beide tragen dieselben Farben wie die erste Karte. Ein Karussell,
        in dem eine Karte anders gesetzt ist, sieht aus wie ein Versehen.
        """
        spec = draft.visual.model_copy(
            update={
                "headline": karte.text,
                "subline": "",
                "body_lines": [],
                "akzentwort": karte.akzentwort or "",
            }
        )
        fertig = self.settings.media_dir / f"{basis}-k{nummer}.png"
        groesse = self._bildformat

        if roh is None:
            return render_post_image(spec, fertig, groesse=groesse)
        try:
            lege_hook_auf(
                roh,
                fertig,
                text=karte.text,
                spec=spec,
                handle=f"@{identity.handle}",
                groesse=groesse,
            )
        except Exception as exc:  # noqa: BLE001 - dann eben ohne Schrift
            log.warning("Schrift auf Karte %s fehlgeschlagen: %s", nummer, exc)
            return roh
        return fertig

    def _baue_karussell(self, draft, basis: str, identity, report: CycleReport, erstes_roh=None):
        """Die weiteren Bilder eines Beitrags. Leer heisst: ein Bild genuegt.

        Der Agent entscheidet die Anzahl am Fund, nicht an einer Regel -
        ein starkes Bild schlaegt fuenf, von denen drei nichts sagen.
        Hier wird nur ausgefuehrt, was er beschlossen hat.

        In drei Schritten, und die Reihenfolge ist der ganze Sinn: erst
        alle nackten Bilder holen, dann die ganze Reihe aneinander
        angleichen, dann beschriften. Wer jedes Bild einzeln angleicht,
        bekommt fuenf Bilder, die jedes fuer sich stimmig sind und
        nebeneinander auseinanderfallen.
        """
        from .imaging.angleichen import gleiche_reihe_an

        # Vorher der Sonderfall, der jedes Faktenkarussell schlaegt: Liegt
        # eine sehr breite Aufnahme vor, wird sie zerschnitten. Wer dann
        # wischt, faehrt an einem Bild entlang statt durch Kacheln zu
        # blaettern - und wischt bis zum Ende.
        pano_erstes, pano_weitere = self._panorama_karussell(
            draft, basis, identity, erstes_roh
        )
        if pano_weitere:
            report.steps.append(
                f"Panorama in {len(pano_weitere) + 1} Stuecke zerschnitten - "
                "man wandert durch die Aufnahme"
            )
            return pano_weitere, [], pano_erstes

        karten = list(getattr(draft, "karten", None) or [])
        if not karten:
            return [], [], None

        # Instagram nimmt bis zu zehn, aber mehr als vier zusaetzliche
        # liest ohnehin niemand zu Ende.
        karten = karten[:4]

        rohbilder: list[Path | None] = []
        nachweise: list[str] = []
        genommen: list = []
        for nummer, karte in enumerate(karten, start=2):
            try:
                self.treasury.check()
            except (BudgetExhausted, CycleBudgetExceeded) as exc:
                report.steps.append(f"Karte {nummer} entfaellt: {exc}")
                break
            roh, nachweis = self._karte_rohbild(karte, basis, nummer)
            rohbilder.append(roh)
            genommen.append(karte)
            if nachweis:
                nachweise.append(nachweis)

        if not genommen:
            return [], [], None

        # Die ganze Reihe auf einen Nenner. Das erste Bild gibt den Ton
        # an und bleibt, wie es ist - es ist das, was im Feed erscheint.
        reihe = [b for b in [erstes_roh, *rohbilder] if b is not None]
        if len(reihe) > 1:
            angeglichen = gleiche_reihe_an(
                reihe,
                hintergrund_hex=draft.visual.background_hex,
                akzent_hex=draft.visual.accent_hex,
            )
            log.info("Karussell: %s von %s Bildern angeglichen", angeglichen, len(reihe))

        # Die Grundbilder ohne Schrift werden aufgehoben: Damit lässt sich
        # später nur der Text einer Karte ändern, ohne ein neues Bild.
        self._letzte_kartenroh = [str(r) if r else None for r in rohbilder]

        bilder: list[Path] = []
        for versatz, (karte, roh) in enumerate(zip(genommen, rohbilder)):
            bilder.append(
                self._beschrifte_karte(karte, roh, basis, versatz + 2, draft, identity)
            )

        report.steps.append(
            f"Karussell: {len(bilder) + 1} Bilder"
            + (f", davon {len(nachweise)} echte Aufnahmen" if nachweise else "")
        )
        return bilder, nachweise, None

    def _erzeuge_bild(
        self, draft, basis: str, identity, report: CycleReport, fund=None
    ) -> tuple[Path | None, Path | None]:
        """Lässt das Bild malen und legt den Hook darüber.

        Gibt das fertige Bild und das Grundbild ohne Schrift zurück, beide
        None, wenn es nicht geklappt hat - dann bleibt es bei der
        Typografie. Ein fehlendes Bild darf nie den Zyklus kosten.

        Das Grundbild wird aufgehoben, weil sich beim Nachbessern oft nur
        die Schrift ändert. Ein zweites Mal zu malen hieße ein anderes
        Motiv, und das war nicht beanstandet.
        """
        # Erst nach einer echten Aufnahme sehen, und zwar bevor irgendetwas
        # anderes geprüft wird. Sie schlägt jedes gemalte Bild, weil sie die
        # Sache zeigt und nicht eine Vorstellung davon - und sie braucht
        # keinen Bilddienst, kein Guthaben und kein Kontingent. Das stand
        # hier lange hinter der Prüfung auf den Bildgenerator: Wer keinen
        # eingerichtet hatte, bekam auch dann kein Foto, wenn eines frei
        # verfügbar dalag.
        probe = (
            getattr(self, "_bildproben", {}).pop(id(fund), None)
            if fund is not None
            else None
        )
        if probe is not None:
            # Schon bei der Stoffsuche gesucht - nicht noch einmal.
            echt, nachweis = probe.echt, probe.nachweis
            self._quellbilder = list(probe.quellbilder)
            self._bildthema = probe.bildthema
        else:
            echt, nachweis = self._echtes_bild(fund, basis, report)
        # Proben zu Funden, die nicht genommen wurden, gehoeren zu keinem
        # Beitrag. Liegen gelassen, faende der naechste Zyklus sie wieder.
        self._bildproben = {}
        if echt is not None:
            self._letzter_nachweis = nachweis
            fertig = self.settings.media_dir / f"{basis}-fertig.png"
            try:
                lege_hook_auf(
                    echt,
                    fertig,
                    text=draft.bildtext,
                    spec=draft.visual,
                    handle=f"@{identity.handle}",
                    groesse=self._bildformat,
                )
            except Exception as exc:  # noqa: BLE001 - dann eben ohne Schrift
                log.warning("Hook auf echtem Bild fehlgeschlagen: %s", exc)
                return echt, echt
            report.steps.append("Echte Aufnahme beschriftet")
            return fertig, echt

        self._letzter_nachweis = ""
        if self.bildgenerator is None:
            # Nur melden, wenn der Betreiber einen Dienst eingerichtet hat -
            # sonst ist die Typografie ja die bewusste Wahl.
            if self.settings.bild.aktiv:
                report.steps.append("Bilddienst eingerichtet, aber nicht aufgebaut")
                self.store.log("image_error", "Der Bilddienst liess sich nicht aufbauen")
            return None, None

        if not draft.image_generation_prompt.strip():
            report.steps.append("Kein Bild-Prompt geschrieben - Typografie bleibt")
            return None, None

        roh = self.settings.media_dir / f"{basis}-roh.png"
        try:
            self.bildgenerator.erzeuge(draft.image_generation_prompt, roh)
        except KontingentErschoepft as exc:
            # Fuer heute ist Schluss. Das gilt auch fuer die naechsten
            # Beitraege in diesem Lauf - und fuer die Bildsprache, deren
            # ueberarbeiteter Prompt sonst umsonst bezahlt waere.
            self._bilder_heute_aus = str(exc)
            log.warning("Bilderzeugung fehlgeschlagen: %s", exc)
            report.steps.append(f"Bild nicht erzeugt ({exc}) - Typografie bleibt")
            self.store.log("image_error", str(exc))
            return None, None
        except Exception as exc:  # noqa: BLE001 - jeder Fehler ist hier verkraftbar
            log.warning("Bilderzeugung fehlgeschlagen: %s", exc)
            report.steps.append(f"Bild nicht erzeugt ({exc}) - Typografie bleibt")
            self.store.log("image_error", str(exc))
            return None, None

        # Erst buchen, wenn wirklich ein Bild da ist - und nur, wenn es
        # etwas gekostet hat. Auf dem eigenen Rechner ist der Preis null.
        if (preis := self.settings.bild.kosten_pro_bild_usd) > 0:
            self.treasury.charge(
                preis,
                category="image",
                note=f"Bild ({self.settings.bild.modell or self.settings.bild.anbieter})",
            )

        fertig = self.settings.media_dir / f"{basis}-fertig.png"
        try:
            lege_hook_auf(
                roh,
                fertig,
                text=draft.bildtext,
                spec=draft.visual,
                handle=f"@{identity.handle}",
                groesse=self._bildformat,
            )
        except Exception as exc:  # noqa: BLE001 - lieber ohne Schrift als gar nicht
            log.warning("Hook konnte nicht aufgelegt werden: %s", exc)
            report.steps.append("Bild erzeugt, Hook-Text konnte nicht aufgelegt werden")
            return roh, roh

        report.steps.append("Bild erzeugt und beschriftet")
        return fertig, roh

    def veroeffentliche_jetzt(self) -> CycleReport:
        """Schickt raus, was freigegeben ist - ohne einen Denkzyklus.

        Veröffentlichen kostet kein Guthaben: Es wird nichts geschrieben
        und nichts gedacht, nur hochgeladen. Es wäre absurd, dafür einen
        bezahlten Zyklus zu verlangen, nur weil das Verschicken sonst am
        Anfang eines Zyklus passiert.
        """
        bericht = CycleReport(cycle=0, started_at=datetime.now(timezone.utc))
        self._veroeffentliche_freigegebenes(bericht)
        bericht.finished_at = datetime.now(timezone.utc)
        return bericht

    def _veroeffentliche_freigegebenes(self, report: CycleReport) -> None:
        """Schickt raus, was der Betreiber freigegeben hat.

        Läuft vor dem Schreiben neuer Beiträge - so ist das Freigegebene
        draußen, auch wenn das Budget für den Rest des Zyklus nicht reicht.
        """
        for zeile in self.store.approved_drafts(limit=5):
            draft = PostDraft.model_validate_json(zeile["draft_json"])
            bild = Path(zeile["image_path"]) if zeile["image_path"] else None
            if bild is None or not bild.exists():
                self.store.mark_failed(zeile["id"], "Das Bild fehlt auf der Festplatte")
                report.steps.append(f"Beitrag {zeile['id']}: Bild fehlt")
                continue

            # Die Bilder zum Durchwischen, falls es welche gibt. Fehlt
            # eines auf der Festplatte, faellt nur dieses weg - der
            # Beitrag geht mit den uebrigen hinaus.
            weitere = [
                pfad
                for roh in json.loads(zeile["karussell_json"] or "[]")
                if (pfad := Path(roh)).exists()
            ]

            # Der Bildnachweis geht mit hinaus: Bei einem übernommenen
            # Foto ist er die Bedingung der Lizenz.
            # Als Reel, wenn der Betreiber es so gewählt hat - mit einem
            # Video, das auf dem Stand der Bilder ist.
            reel = None
            if self.store.get_json(f"format:{zeile['id']}") == "reel":
                stand = self.reel_stand(zeile["id"], zeile)
                if not stand["aktuell"]:
                    self.reel_bauen(zeile["id"])
                if pfad := self.store.get_json(f"reel:{zeile['id']}"):
                    reel = Path(pfad) if Path(pfad).is_file() else None

            extra = {"reel": reel} if reel is not None else {}
            ergebnis = self.publisher.publish(
                draft, bild, zeile["bildnachweis"] or "", weitere=weitere, **extra
            )
            if ergebnis.published and ergebnis.ig_media_id:
                self.store.mark_published(zeile["id"], ergebnis.ig_media_id)
                report.published_media_ids.append(ergebnis.ig_media_id)
                report.steps.append(f"Veröffentlicht: {ergebnis.ig_media_id}")
            else:
                # Freigegeben bleibt freigegeben - beim nächsten Mal erneut.
                self.store.mark_failed(zeile["id"], ergebnis.reason or "unbekannt")
                report.steps.append(f"Beitrag {zeile['id']} wartet: {ergebnis.reason}")

    def _pruefe_kurs(self, cycle: int, identity, performance: str, report: CycleReport):
        """Rechnet nach, ob ein anderer Weg mehr einbringt.

        Gibt die Identität zurück, mit der weitergearbeitet wird - die alte
        oder eine neue.
        """
        letzter_wechsel = int(self.store.get_json(KEY_LAST_PIVOT) or 0)

        bewertung = assess_opportunities(
            self.brain,
            identity=identity,
            treasury_state=self.treasury.state(),
            follower_count=int(self.store.latest_metric("followers") or 0),
            performance=performance,
            wallet_hinweis=self.wallet_hinweis,
            zyklen_seit_wechsel=cycle - letzter_wechsel,
        )
        self.store.set_json(KEY_ASSESSMENT, bewertung)

        beste = max(
            bewertung.opportunities, key=lambda o: o.expected_value_usd, default=None
        )
        bester_wert = beste.expected_value_usd if beste else 0.0
        report.steps.append(
            f"Kursprüfung: jetziger Weg {bewertung.current_path_value_usd:.0f} USD, "
            f"beste Alternative {bester_wert:.0f} USD → {bewertung.recommendation}"
        )
        self.store.log(
            "assessment",
            f"{bewertung.recommendation}: {bewertung.reasoning[:200]}",
            cycle,
            payload=bewertung.model_dump(mode="json"),
        )

        grund = self._wechsel_abgelehnt(bewertung, beste, cycle, letzter_wechsel)
        if grund:
            report.steps.append(f"Kein Wechsel: {grund}")
            self.store.log("assessment", f"Wechsel abgelehnt: {grund}", cycle)
            return identity

        return self._wechsle(cycle, identity, bewertung, beste, report)

    def _wechsel_abgelehnt(self, bewertung, beste, cycle: int, letzter_wechsel: int) -> str | None:
        """Prüft die harten Bedingungen für einen Kurswechsel.

        Der Agent darf wechseln - aber nicht aus einer Laune heraus. Jede
        Bedingung hier hat einen Grund, der Geld kostet, wenn man sie
        weglässt.
        """
        if bewertung.recommendation == "weitermachen":
            return "er will bei seinem Kurs bleiben"
        if bewertung.recommendation == "ergaenzen":
            return "er will zusätzlich verdienen, ohne die Nische zu verlassen"

        if beste is None:
            return "keine Alternative benannt"

        abstand = cycle - letzter_wechsel
        if letzter_wechsel and abstand < PIVOT_MINDESTABSTAND:
            return (
                f"erst {abstand} Zyklen seit dem letzten Wechsel, "
                f"Mindestabstand sind {PIVOT_MINDESTABSTAND}"
            )

        if bewertung.confidence == "low":
            return "die eigene Einschätzung ist zu unsicher"

        schwelle = max(bewertung.current_path_value_usd * PIVOT_FAKTOR, 1.0)
        if beste.expected_value_usd < schwelle:
            return (
                f"die Alternative bringt im Mittel {beste.expected_value_usd:.0f} USD, "
                f"nötig wären {schwelle:.0f} USD"
            )

        return None

    def _wechsle(self, cycle: int, alt, bewertung, beste, report: CycleReport):
        """Richtet den Agenten neu aus und bewahrt auf, was vorher war."""
        verlauf = self.store.get_json(KEY_IDENTITY_HISTORY) or []
        verlauf.append(
            {
                "zyklus": cycle,
                "identitaet": alt.model_dump(mode="json"),
                "grund_des_wechsels": bewertung.reasoning,
                "neue_richtung": beste.name,
            }
        )
        self.store.set_json(KEY_IDENTITY_HISTORY, verlauf)

        analyse = run_market_research(self.brain, identity=alt, focus=beste.description)
        self.store.set_json(KEY_ANALYSIS, analyse)

        neu = invent_identity(
            self.brain,
            analyse,
            operator_hint=(
                f"Du richtest dich neu aus. Bisher warst du @{alt.handle} "
                f"({alt.niche}). Du wechselst, weil: {bewertung.reasoning} "
                f"Die neue Richtung ist: {beste.description} "
                f"Behalte deinen Namen {alt.agent_name} - du bleibst dieselbe Person, "
                "nur dein Geschäft ändert sich."
            ),
        )
        neu.agent_name = alt.agent_name  # Die Person bleibt, die Marke wechselt.
        neu.agent_why = alt.agent_why

        self.store.set_json(KEY_IDENTITY, neu)
        self.store.set_json(KEY_LAST_PIVOT, cycle)
        # Der alte Kurs gilt nicht mehr, sonst plant er gegen sich selbst.
        self.store.set_json(KEY_STRATEGY, None)

        report.steps.append(f"Neuausrichtung: @{alt.handle} → @{neu.handle} ({beste.name})")
        self.store.log(
            "pivot",
            f"@{alt.handle} → @{neu.handle}, weil: {bewertung.reasoning[:200]}",
            cycle,
            payload={"vorher": alt.handle, "nachher": neu.handle, "grund": bewertung.reasoning},
        )
        return neu

    def _plan_monetization(
        self, cycle: int, identity, performance: str, report: CycleReport
    ) -> None:
        plan = build_monetization_plan(
            self.brain,
            identity=identity,
            treasury_state=self.treasury.state(),
            follower_count=int(self.store.latest_metric("followers") or 0),
            performance=performance,
            wallet_hinweis=self.wallet_hinweis,
        )
        self.store.set_json(KEY_MONETIZATION, plan)
        self.store.log(
            "monetization",
            f"Neuer Geschäftsplan, jetzt startet: {plan.recommended_now}",
            cycle,
            payload=plan.model_dump(mode="json"),
        )
        report.steps.append(f"Geschäftsplan: {plan.recommended_now}")


def _erklaere_api_fehler(exc: anthropic.APIStatusError) -> str:
    """Übersetzt einen Fehler der Claude API in einen brauchbaren Hinweis."""
    text = str(exc).lower()

    if exc.status_code == 401:
        return (
            "Die Claude API weist den Schlüssel zurück. Entweder stimmt er nicht, "
            "oder er wurde gelöscht oder ist abgelaufen. Leg unter "
            "console.anthropic.com → Settings → API keys einen neuen an und trag "
            "ihn mit `insta-agent setup` ein."
        )
    if exc.status_code == 400 and ("credit" in text or "balance" in text):
        return (
            "Das Guthaben deines Anthropic-Kontos ist aufgebraucht. Lad unter "
            "console.anthropic.com → Settings → Billing etwas auf - das ist von "
            "der internen Kasse des Agenten unabhängig, die zählt nur mit."
        )
    if exc.status_code == 429:
        return (
            "Zu viele Anfragen in kurzer Zeit. Warte ein paar Minuten und starte "
            "den Zyklus erneut."
        )
    if exc.status_code >= 500:
        return (
            f"Die Claude API hat einen Serverfehler gemeldet ({exc.status_code}). "
            "Das liegt nicht an dir - versuch es später nochmal."
        )
    return f"Die Claude API hat abgelehnt ({exc.status_code}): {exc}"
