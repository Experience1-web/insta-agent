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

        # Reflektieren, sobald es überhaupt etwas zu reflektieren gibt.
        reflection = self.reflection
        if self.store.published_count() > 0:
            reflection = reflect(
                self.brain,
                identity=identity,
                strategy=self.strategy,
                performance=performance,
                post_history=self._post_history(),
            )
            self.store.set_json(KEY_REFLECTION, reflection)
            report.steps.append("Reflexion abgeschlossen")

        # Recherche kostet - nur in festem Takt oder wenn der Kurs wackelt.
        analysis = self.analysis
        due = cycle % RESEARCH_EVERY == 0
        wants_change = bool(reflection and reflection.strategy_should_change)
        if (due or wants_change) and state.mode is Mode.NORMAL:
            analysis = run_market_research(self.brain, identity=identity)
            self.store.set_json(KEY_ANALYSIS, analysis)
            report.steps.append(f"Marktrecherche ({len(analysis.sources)} Quellen)")

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
        report.steps.append(f"Ziel: {strategy.current_goal}")

        # Lohnt sich der Kurs noch? Nicht in jedem Zyklus - das kostet.
        if cycle % ASSESS_EVERY == 0 and state.mode is Mode.NORMAL:
            identity = self._pruefe_kurs(cycle, identity, performance, report)

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
            weitere, karten_nachweise, ersatz = self._baue_karussell(
                draft, basis, identity, report, erstes_roh=rohbild
            )
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
        karten = list(getattr(draft, "karten", None) or [])
        if versatz >= len(karten):
            return {"ok": False, "grund": "Zu diesem Bild gibt es keine Karte."}

        self.treasury.check()
        vorher = self.treasury.state().cycle_spent_usd

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        basis = f"{stamp}-neu-{post_id}"
        karte = karten[versatz]
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

        kosten = self._mitrechnen(post_id, vorher)
        self.store.log(
            "bild_neu",
            f"Entwurf {post_id}: Bild {stelle} neu ({kosten:.4f} USD)",
        )
        return {"ok": True, "gemalt": roh is not None, "stelle": stelle, "schritte": []}

    def bild_neu(self, post_id: int) -> dict:
        """Malt das Bild eines Entwurfs neu, ohne den Text anzufassen.

        Gedacht fuer den Fall, dass einem das Bild einfach nicht gefaellt.
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

        gestaltung = self._gestalte(draft, identity, lauf)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        basis = f"{stamp}-neu-{post_id}"
        bild = render_post_image(
            draft.visual,
            self.settings.media_dir / f"{basis}.png",
            groesse=self._bildformat,
        )
        fund = (
            Fund.model_validate(json.loads(zeile["fund_json"])) if zeile["fund_json"] else None
        )
        gemalt, rohbild = self._erzeuge_bild(draft, basis, identity, lauf, fund)
        if gemalt:
            bild = gemalt

        self.store.setze_bild(post_id, draft, str(bild))
        self.store.setze_rohbild(post_id, str(rohbild) if rohbild else None)
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

        self.store.ersetze_entwurf(post_id, neu, str(bild))

        # Und noch einmal durch dieselbe Prüfung - sonst wäre die
        # Nachbesserung nur eine Behauptung.
        #
        # Reicht das Geld dafür nicht mehr, bleibt ein neu geschriebener
        # Entwurf ohne Bericht liegen. Der sieht dann aus wie einer, den
        # nie jemand geprüft hat - und das ist die gefährlichste aller
        # Anzeigen. Also wenigstens ins Protokoll damit.
        try:
            zweiter = self._pruefe(post_id, neu, identity, bericht_lauf, fund)
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
        if zeile["pruefung_json"]:
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
                gefunden = finde_und_hole(suchwort, ziel)
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
        )
        self.store.log("bild_echt", f"{gefunden.seite} - {gefunden.lizenz}")
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
        return STORY if self.settings.posting.bildformat == "story" else FEED

    def _karte_rohbild(self, karte, basis: str, nummer: int):
        """Das nackte Bild einer Karte - echt oder gemalt, noch ohne Schrift.

        Getrennt von der Beschriftung, und das ist der Punkt: Angeglichen
        wird die ganze Reihe auf einmal, und das geht nur, solange noch
        keine Schrift darauf liegt. Sonst wuerde die Helligkeitskorrektur
        den Text mit verschieben.
        """
        stamm = f"{basis}-k{nummer}"

        # Eine echte Aufnahme schlaegt jedes gemalte Bild.
        if suchwort := (karte.bildsuche or "").strip():
            from .imaging.echtbild import finde_und_hole

            ziel = self.settings.media_dir / f"{stamm}-echt.jpg"
            try:
                gefunden = finde_und_hole(suchwort, ziel)
            except Exception as exc:  # noqa: BLE001 - dann wird gemalt
                log.info("Kartensuche fehlgeschlagen: %s", exc)
                gefunden = None
            if gefunden is not None and gefunden.pfad is not None:
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
        echt, nachweis = self._echtes_bild(fund, basis, report)
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
            ergebnis = self.publisher.publish(
                draft, bild, zeile["bildnachweis"] or "", weitere=weitere
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
