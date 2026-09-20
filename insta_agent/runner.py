"""Der Arbeitszyklus des Agenten.

Ein Zyklus ist ein Arbeitstag: nachsehen, was die Zahlen sagen, daraus
lernen, den Kurs nachziehen, etwas veröffentlichen und ab und zu darüber
nachdenken, wie der Account Geld verdienen soll.

Alles Wissen liegt zwischen den Zyklen in der SQLite-Datei. Der Agent kann
jederzeit angehalten und später fortgesetzt werden, ohne sein Gedächtnis zu
verlieren.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from .brain import (
    assess_opportunities,
    build_monetization_plan,
    create_post_draft,
    invent_identity,
    reflect,
    run_market_research,
    update_strategy,
)
from .config import Settings
from .economy.ledger import BudgetExhausted, CycleBudgetExceeded, Mode, Treasury
from .imaging import FEED, STORY, lege_hook_auf, render_post_image
from .imaging.generator import baue_generator
from .instagram import InstagramClient, Publisher
from .llm import Brain, ModelRefused
from .models import (
    CycleReport,
    Identity,
    MarketAnalysis,
    MonetizationPlan,
    OpportunityAssessment,
    PostDraft,
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
        self.brain = Brain(settings.llm, self.treasury, settings.anthropic_api_key)

        self.ig: InstagramClient | None = None
        if settings.instagram_ready:
            self.ig = InstagramClient(settings.ig_user_id, settings.ig_access_token)

        from .instagram.ablage import baue_ablage

        self.ablage = baue_ablage(settings.ablage_anbieter, settings.ablage_token)
        self.publisher = Publisher(
            client=self.ig,
            media_dir=settings.media_dir,
            draft_dir=settings.draft_dir,
            public_base_url=settings.public_media_base_url,
            live=settings.posting.live,
            ablage=self.ablage,
        )

        # Ohne Schlüssel bleibt es bei der Typografie - kein Fehler, nur weniger.
        self.bildgenerator = baue_generator(
            settings.bild.anbieter, settings.bild.token, settings.bild.modell
        )

    def close(self) -> None:
        if self.ig:
            self.ig.close()
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
        """Der Agent erfindet sich selbst. Passiert genau einmal."""
        if existing := self.identity:
            return existing

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

    # -- Ein Zyklus --------------------------------------------------------

    def run_cycle(self, *, operator_hint: str | None = None) -> CycleReport:
        cycle = self.store.next_cycle_number()
        report = CycleReport(started_at=datetime.now(timezone.utc))
        self.treasury.begin_cycle()

        try:
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

            draft = create_post_draft(
                self.brain,
                identity=identity,
                strategy=strategy,
                recent_captions=recent,
                max_hashtags=self.settings.posting.max_hashtags,
                performance_note=performance,
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
                groesse=STORY if self.settings.posting.bildformat == "story" else FEED,
            )
            if erzeugt := self._erzeuge_bild(draft, basis, identity, report):
                image_path = erzeugt
            post_id = self.store.add_draft(draft, str(image_path))

            report.drafts_written.append(str(image_path))
            if self.settings.posting.freigabe_noetig:
                # Der Normalfall: Der Beitrag wartet auf das Ja des
                # Betreibers. Erst der nächste Zyklus schickt raus, was
                # freigegeben wurde.
                report.steps.append(f"Entwurf {post_id} wartet auf Freigabe")
            else:
                # Autopilot: Der Betreiber hat die Freigabepflicht
                # abgeschaltet. Dann geht der Beitrag mit dem nächsten
                # Zyklus von selbst hinaus.
                self.store.freigeben(post_id)
                report.steps.append(f"Entwurf {post_id} automatisch freigegeben")

            recent.append(draft.caption)

    def _erzeuge_bild(self, draft, basis: str, identity, report: CycleReport) -> Path | None:
        """Lässt das Bild malen und legt den Hook darüber.

        Gibt None zurück, wenn es nicht geklappt hat - dann bleibt es bei
        der Typografie. Ein fehlendes Bild darf nie den Zyklus kosten.
        """
        if self.bildgenerator is None:
            # Nur melden, wenn der Betreiber einen Dienst eingerichtet hat -
            # sonst ist die Typografie ja die bewusste Wahl.
            if self.settings.bild.aktiv:
                report.steps.append("Bilddienst eingerichtet, aber nicht aufgebaut")
                self.store.log("image_error", "Der Bilddienst liess sich nicht aufbauen")
            return None

        if not draft.image_generation_prompt.strip():
            report.steps.append("Kein Bild-Prompt geschrieben - Typografie bleibt")
            return None

        roh = self.settings.media_dir / f"{basis}-roh.png"
        try:
            self.bildgenerator.erzeuge(draft.image_generation_prompt, roh)
        except Exception as exc:  # noqa: BLE001 - jeder Fehler ist hier verkraftbar
            log.warning("Bilderzeugung fehlgeschlagen: %s", exc)
            report.steps.append(f"Bild nicht erzeugt ({exc}) - Typografie bleibt")
            self.store.log("image_error", str(exc))
            return None

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
            )
        except Exception as exc:  # noqa: BLE001 - lieber ohne Schrift als gar nicht
            log.warning("Hook konnte nicht aufgelegt werden: %s", exc)
            report.steps.append("Bild erzeugt, Hook-Text konnte nicht aufgelegt werden")
            return roh

        report.steps.append("Bild erzeugt und beschriftet")
        return fertig

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

            ergebnis = self.publisher.publish(draft, bild)
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
