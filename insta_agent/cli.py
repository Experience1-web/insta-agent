"""Kommandozeile: hier steuerst du den Agenten.

Der wichtigste Befehl ist `run`. Alles andere dient dazu, nachzusehen, was
der Agent denkt, plant und ausgibt.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import load_settings
from .runner import Agent

app = typer.Typer(
    add_completion=False,
    help="Ein Agent, der einen Instagram-Account erfindet, führt und finanziert.",
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Die HTTP-Bibliotheken sind sonst sehr gesprächig.
    for noisy in ("httpx", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _agent(config: Path | None) -> Agent:
    return Agent(load_settings(config))


# --------------------------------------------------------------------------


@app.command()
def run(
    cycles: int = typer.Option(1, help="Wie viele Zyklen nacheinander laufen sollen."),
    interval: int = typer.Option(0, help="Pause zwischen den Zyklen in Sekunden."),
    hint: str = typer.Option(
        "", help="Optionaler Wunsch für die Nische. Ohne Angabe entscheidet der Agent allein."
    ),
    live: bool = typer.Option(
        False, "--live", help="Wirklich veröffentlichen. Ohne diese Option nur Entwürfe."
    ),
    config: Path = typer.Option(None, help="Eigene Konfigurationsdatei."),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Lässt den Agenten arbeiten."""
    _setup_logging(verbose)
    settings = load_settings(config)
    if live:
        settings.posting.live = True

    if settings.posting.live and not settings.can_publish:
        console.print(
            "[yellow]--live gesetzt, aber es fehlen Zugangsdaten oder die öffentliche "
            "Bild-URL. Der Agent legt stattdessen Entwürfe ab.[/yellow]"
        )

    agent = Agent(settings)
    try:
        for index in range(cycles):
            console.rule(f"Zyklus {index + 1} von {cycles}")
            report = agent.run_cycle(operator_hint=hint or None)

            for step in report.steps:
                console.print(f"  [dim]·[/dim] {step}")
            console.print(f"\n  Kosten dieses Zyklus: [bold]{report.cost_usd:.4f} USD[/bold]")

            if report.drafts_written:
                console.print(f"  Entwürfe: {', '.join(report.drafts_written)}")
            if report.halted_reason:
                console.print(f"  [red]Abgebrochen: {report.halted_reason}[/red]")
                break

            if interval and index + 1 < cycles:
                console.print(f"  [dim]Pause {interval}s …[/dim]")
                time.sleep(interval)

        _print_treasury(agent)
    finally:
        agent.close()


@app.command()
def identity(config: Path = typer.Option(None)) -> None:
    """Zeigt, wer der Agent zu sein beschlossen hat."""
    agent = _agent(config)
    try:
        ident = agent.identity
        if not ident:
            console.print("[yellow]Noch kein Profil. Starte `insta-agent run`.[/yellow]")
            raise typer.Exit(1)
        console.print(
            Panel(
                f"[bold]{ident.motto}[/bold]\n\n"
                f"Handle:      @{ident.handle}\n"
                f"Name:        {ident.display_name}\n"
                f"Nische:      {ident.niche}\n"
                f"Zielgruppe:  {ident.target_audience}\n"
                f"Tonfall:     {ident.tone_of_voice}\n"
                f"Bildsprache: {ident.visual_identity}\n"
                f"Säulen:      {', '.join(ident.content_pillars)}\n\n"
                f"[dim]Bio:[/dim] {ident.bio}\n\n"
                f"[dim]Begründung:[/dim] {ident.why_this_works}",
                title="Das Profil, das der Agent sich gegeben hat",
            )
        )
    finally:
        agent.close()


@app.command()
def strategy(config: Path = typer.Option(None)) -> None:
    """Zeigt den aktuellen Kurs."""
    agent = _agent(config)
    try:
        strat = agent.strategy
        if not strat:
            console.print("[yellow]Noch keine Strategie.[/yellow]")
            raise typer.Exit(1)
        console.print(
            Panel(
                f"[bold]{strat.current_goal}[/bold]\n\n"
                f"{strat.reasoning}\n\n"
                f"Taktung:     {strat.posting_cadence}\n"
                f"Kennzahlen:  {', '.join(strat.kpis_to_watch)}\n"
                f"Änderungen:  {'; '.join(strat.changes) or 'keine'}\n"
                f"Experimente: {'; '.join(strat.experiments) or 'keine'}",
                title="Kurs der Woche",
            )
        )
    finally:
        agent.close()


@app.command()
def money(config: Path = typer.Option(None)) -> None:
    """Zeigt Kassenstand und Geschäftsplan."""
    agent = _agent(config)
    try:
        _print_treasury(agent)

        plan = agent.monetization
        if not plan:
            console.print("\n[dim]Noch kein Geschäftsplan erstellt.[/dim]")
            return

        table = Table(title="Geschäftsideen des Agenten")
        table.add_column("Idee", style="bold")
        table.add_column("Modell")
        table.add_column("Preis", justify="right")
        table.add_column("ab Followern", justify="right")
        table.add_column("Aufwand")
        table.add_column("USD/Monat", justify="right")
        for idea in plan.ideas:
            marker = " ←" if idea.name == plan.recommended_now else ""
            table.add_row(
                idea.name + marker,
                idea.revenue_model,
                f"{idea.price_point_usd:.2f}",
                str(idea.required_followers),
                idea.effort,
                f"{idea.monthly_revenue_estimate_usd:.0f}",
            )
        console.print(table)
        console.print(f"\n[bold]Startet jetzt:[/bold] {plan.recommended_now}")
        console.print("\n[bold]Was du selbst erledigen musst:[/bold]")
        for step in plan.what_the_operator_must_do:
            console.print(f"  [ ] {step}")
    finally:
        agent.close()


@app.command()
def earn(
    amount: float = typer.Argument(..., help="Betrag in USD, den der Account eingebracht hat."),
    category: str = typer.Option(
        "other",
        help="digital_product, affiliate, sponsorship, service, subscription oder other.",
    ),
    note: str = typer.Option("", help="Wofür das Geld kam."),
    config: Path = typer.Option(None),
) -> None:
    """Meldet dem Agenten eine Einnahme.

    Geld empfangen kann nur ein Mensch. Sobald auf deinem Konto etwas
    ankommt, das dieser Account eingebracht hat, buchst du es hier ein -
    erst dann sieht der Agent, dass er seine eigenen Kosten deckt.
    """
    if amount <= 0:
        console.print("[red]Der Betrag muss größer als null sein.[/red]")
        raise typer.Exit(1)

    agent = _agent(config)
    try:
        agent.treasury.earn(amount, category, note)
        agent.store.log("revenue", f"Einnahme {amount:.2f} USD ({category}): {note}")
        console.print(f"[green]{amount:.2f} USD als '{category}' gebucht.[/green]\n")
        _print_treasury(agent)
    finally:
        agent.close()


@app.command()
def drafts(
    limit: int = typer.Option(5, help="Wie viele Entwürfe angezeigt werden."),
    config: Path = typer.Option(None),
) -> None:
    """Listet die noch nicht veröffentlichten Entwürfe."""
    agent = _agent(config)
    try:
        rows = agent.store.pending_drafts(limit)
        if not rows:
            console.print("[dim]Keine offenen Entwürfe.[/dim]")
            return
        for row in rows:
            draft = json.loads(row["draft_json"])
            console.print(
                Panel(
                    f"{draft['caption']}\n\n"
                    f"[dim]{' '.join('#' + h for h in draft['hashtags'])}[/dim]\n\n"
                    f"[dim]Bild: {row['image_path']}[/dim]",
                    title=f"#{row['id']} · {row['pillar']} · {draft['best_time_hint']}",
                )
            )
    finally:
        agent.close()


@app.command()
def journal(
    limit: int = typer.Option(20, help="Wie viele Einträge angezeigt werden."),
    config: Path = typer.Option(None),
) -> None:
    """Zeigt das Arbeitsprotokoll des Agenten."""
    agent = _agent(config)
    try:
        table = Table(title="Protokoll")
        table.add_column("Zeit", style="dim")
        table.add_column("Zyklus", justify="right")
        table.add_column("Art")
        table.add_column("Eintrag")
        for row in reversed(agent.store.recent_journal(limit)):
            table.add_row(
                row["occurred_at"][:19].replace("T", " "),
                str(row["cycle"] or "-"),
                row["kind"],
                row["message"][:90],
            )
        console.print(table)
    finally:
        agent.close()


@app.command("token-refresh")
def token_refresh(config: Path = typer.Option(None)) -> None:
    """Erneuert den Instagram-Token, der sonst nach ~60 Tagen abläuft."""
    settings = load_settings(config)
    if not (settings.instagram_ready and settings.meta_app_id and settings.meta_app_secret):
        console.print("[red]IG_ACCESS_TOKEN, META_APP_ID und META_APP_SECRET werden gebraucht.[/red]")
        raise typer.Exit(1)

    from .instagram import InstagramClient

    with InstagramClient(settings.ig_user_id, settings.ig_access_token) as client:
        token, expires_in = client.refresh_long_lived_token(
            settings.meta_app_id, settings.meta_app_secret
        )
    console.print(f"Neuer Token gültig für {expires_in // 86400} Tage.")
    console.print("[bold]Trage ihn in .env ein:[/bold]")
    console.print(f"IG_ACCESS_TOKEN={token}")


def _print_treasury(agent: Agent) -> None:
    state = agent.treasury.state()
    color = {"normal": "green", "frugal": "yellow", "halted": "red"}[state.mode.value]
    console.print(
        Panel(
            f"Einlage des Betreibers: {state.seed_usd:>10.2f} USD\n"
            f"Selbst verdient:        {state.earned_usd:>10.2f} USD\n"
            f"Ausgegeben:             {state.spent_usd:>10.4f} USD\n"
            f"[bold]Kontostand:             {state.balance_usd:>10.4f} USD[/bold]\n\n"
            f"Modus:                  [{color}]{state.mode.value}[/{color}]\n"
            f"Kostendeckung:          {state.cost_coverage * 100:>9.0f} %\n"
            f"Trägt sich selbst:      {'ja' if state.self_sustaining else 'noch nicht':>11}",
            title="Kasse",
        )
    )


if __name__ == "__main__":
    app()
