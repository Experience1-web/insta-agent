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

from .brain import (
    build_monetization_plan,
    create_post_draft,
    invent_identity,
    reflect,
    run_market_research,
    update_strategy,
)
from .config import Settings
from .economy.ledger import BudgetExhausted, CycleBudgetExceeded, Mode, Treasury
from .imaging import render_post_image
from .instagram import InstagramClient, Publisher
from .llm import Brain, ModelRefused
from .models import CycleReport, Identity, MarketAnalysis, MonetizationPlan, Reflection, StrategyUpdate
from .store import Store

log = logging.getLogger(__name__)

KEY_IDENTITY = "identity"
KEY_STRATEGY = "strategy"
KEY_ANALYSIS = "market_analysis"
KEY_REFLECTION = "reflection"
KEY_MONETIZATION = "monetization_plan"

# Recherche und Geschäftsplanung kosten Geld und ändern sich langsam -
# deshalb nicht in jedem Zyklus.
RESEARCH_EVERY = 7
MONETIZATION_EVERY = 14


class Agent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = Store(settings.db_path)
        self.treasury = Treasury(self.store, settings.economy)
        self.brain = Brain(settings.llm, self.treasury, settings.anthropic_api_key)

        self.ig: InstagramClient | None = None
        if settings.instagram_ready:
            self.ig = InstagramClient(settings.ig_user_id, settings.ig_access_token)

        self.publisher = Publisher(
            client=self.ig,
            media_dir=settings.media_dir,
            draft_dir=settings.draft_dir,
            public_base_url=settings.public_media_base_url,
            live=settings.posting.live,
        )

    def close(self) -> None:
        if self.ig:
            self.ig.close()
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

    def bootstrap(self, *, operator_hint: str | None = None, cycle: int = 0) -> Identity:
        """Der Agent erfindet sich selbst. Passiert genau einmal."""
        if existing := self.identity:
            return existing

        log.info("Kein Profil vorhanden - der Agent erfindet sich selbst")
        analysis = run_market_research(self.brain, identity=None, focus=operator_hint)
        self.store.set_json(KEY_ANALYSIS, analysis)

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
            image_path = render_post_image(
                draft.visual, self.settings.media_dir / f"{stamp}-{cycle}-{index}.png"
            )
            post_id = self.store.add_draft(draft, str(image_path))

            result = self.publisher.publish(draft, image_path)
            if result.published and result.ig_media_id:
                self.store.mark_published(post_id, result.ig_media_id)
                report.published_media_ids.append(result.ig_media_id)
                report.steps.append(f"Veröffentlicht: {result.ig_media_id}")
            else:
                if result.draft_path:
                    report.drafts_written.append(str(result.draft_path))
                report.steps.append(f"Entwurf abgelegt ({result.reason})")

            recent.append(draft.caption)

    def _plan_monetization(
        self, cycle: int, identity, performance: str, report: CycleReport
    ) -> None:
        plan = build_monetization_plan(
            self.brain,
            identity=identity,
            treasury_state=self.treasury.state(),
            follower_count=int(self.store.latest_metric("followers") or 0),
            performance=performance,
        )
        self.store.set_json(KEY_MONETIZATION, plan)
        self.store.log(
            "monetization",
            f"Neuer Geschäftsplan, jetzt startet: {plan.recommended_now}",
            cycle,
            payload=plan.model_dump(mode="json"),
        )
        report.steps.append(f"Geschäftsplan: {plan.recommended_now}")
