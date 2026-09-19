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

from .config import ENV_PATH, REPO_ROOT, load_settings, set_env_value
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
def setup() -> None:
    """Richtet den Agenten ein: fragt nach dem API-Schlüssel und legt die .env an.

    Der einfachste Weg. Du musst keine Datei suchen und keinen Editor
    öffnen - dieser Befehl erledigt beides.
    """
    console.print(Panel("Einrichtung des Agenten", style="bold"))
    console.print(f"Die Einstellungen kommen in diese Datei:\n  [bold]{ENV_PATH}[/bold]\n")

    if ENV_PATH.exists():
        console.print("[dim]Die Datei gibt es schon - sie wird ergänzt, nicht überschrieben.[/dim]\n")
    else:
        console.print("[dim]Die Datei gibt es noch nicht - sie wird jetzt angelegt.[/dim]\n")

    console.print("Deinen Schlüssel bekommst du unter console.anthropic.com → Settings → API keys.")
    console.print("[dim]Beim Eintippen bleibt er unsichtbar, das ist Absicht.[/dim]\n")

    roh = typer.prompt("API-Schlüssel", hide_input=True)

    # Beim Einfügen aus der Zwischenablage kommen oft Zeilenumbrüche oder
    # Leerzeichen mit. Ein API-Schlüssel enthält nie welche, also raus damit -
    # sonst zerreißt ein Umbruch die .env und der Schlüssel geht verloren.
    key = "".join(roh.split())
    if key != roh.strip():
        console.print("[dim]Leerzeichen und Zeilenumbrüche aus der Eingabe entfernt.[/dim]")

    if not key:
        console.print("[red]Nichts eingegeben, nichts geändert.[/red]")
        raise typer.Exit(1)
    if not key.startswith("sk-ant-"):
        console.print(
            "[yellow]Achtung: Anthropic-Schlüssel fangen mit 'sk-ant-' an. "
            "Deiner nicht - vermutlich hast du etwas anderes kopiert.[/yellow]"
        )
        if not typer.confirm("Trotzdem eintragen?", default=False):
            raise typer.Exit(1)

    path = set_env_value("ANTHROPIC_API_KEY", key)
    console.print(f"\n[green]Eingetragen in {path}[/green]")

    # Gegenprobe: wird der Schlüssel auch wirklich gelesen?
    import os

    os.environ.pop("ANTHROPIC_API_KEY", None)
    settings = load_settings()
    if settings.anthropic_api_key == key:
        console.print("[green]Gegenprobe bestanden - der Agent findet den Schlüssel.[/green]")
    else:
        console.print(
            "[red]Der Schlüssel wurde geschrieben, aber nicht wieder eingelesen.[/red]\n"
            f"Erwartet: {len(key)} Zeichen, gelesen: "
            f"{len(settings.anthropic_api_key or '')} Zeichen.\n"
            "Sieh mit [bold]insta-agent check[/bold] nach, was in der Datei steht."
        )
        raise typer.Exit(1)

    console.print(
        "\n[bold]Fertig.[/bold] Jetzt kannst du loslegen:\n"
        "  [bold]insta-agent run[/bold]\n\n"
        "[dim]Falls dabei ein Guthaben-Fehler kommt: unter console.anthropic.com "
        "→ Settings → Billing Guthaben aufladen.[/dim]"
    )


@app.command()
def check() -> None:
    """Prüft, ob die Zugangsdaten richtig in der .env stehen.

    Zeigt den Schlüssel nur verkürzt an - genug zum Erkennen, zu wenig zum
    Missbrauchen.
    """
    if not ENV_PATH.exists():
        console.print(f"[red]Es gibt noch keine .env unter {ENV_PATH}[/red]")
        console.print("Leg sie an mit: [bold]insta-agent setup[/bold]")
        raise typer.Exit(1)

    zeilen = ENV_PATH.read_text(encoding="utf-8").splitlines()

    # Zeilen ohne "=" und ohne "#" sind Bruchstücke eines zerrissenen Wertes.
    kaputt = [
        (nummer, zeile)
        for nummer, zeile in enumerate(zeilen, 1)
        if zeile.strip() and not zeile.strip().startswith("#") and "=" not in zeile
    ]
    if kaputt:
        console.print("[red]Kaputte Zeilen in der .env gefunden:[/red]")
        for nummer, zeile in kaputt:
            console.print(f"  Zeile {nummer}: {zeile[:40]!r}")
        console.print(
            "\nDas passiert, wenn beim Einfügen ein Zeilenumbruch mitkam.\n"
            "Lösch diese Zeilen oder trag den Schlüssel neu ein mit "
            "[bold]insta-agent setup[/bold]."
        )

    settings = load_settings()
    schluessel = settings.anthropic_api_key

    table = Table(title="Zugangsdaten")
    table.add_column("Was", style="bold")
    table.add_column("Stand")

    if not schluessel:
        table.add_row("Claude API", "[red]fehlt[/red]")
    elif not schluessel.startswith("sk-ant-"):
        table.add_row("Claude API", f"[yellow]verdächtig: {schluessel[:10]}…[/yellow]")
    else:
        maskiert = f"{schluessel[:11]}…{schluessel[-4:]} ({len(schluessel)} Zeichen)"
        table.add_row("Claude API", f"[green]{maskiert}[/green]")

    table.add_row(
        "Instagram",
        "[green]verbunden[/green]" if settings.instagram_ready else "[dim]nicht nötig für Entwürfe[/dim]",
    )
    table.add_row(
        "Veröffentlichen",
        "[green]möglich[/green]" if settings.can_publish else "[dim]nur Entwürfe[/dim]",
    )
    console.print(table)

    if schluessel and schluessel.startswith("sk-ant-") and not kaputt:
        console.print("\n[green]Alles bereit. Starte mit:[/green] [bold]insta-agent run[/bold]")


@app.command()
def where() -> None:
    """Zeigt, wo die Dateien des Agenten auf deinem Rechner liegen."""
    settings = load_settings()
    table = Table(title="Wo liegt was")
    table.add_column("Was", style="bold")
    table.add_column("Wo")
    table.add_column("Da?")

    eintraege = [
        ("Zugangsdaten (.env)", ENV_PATH),
        ("Einstellungen", REPO_ROOT / "config" / "agent.yaml"),
        ("Gedächtnis", settings.db_path),
        ("Entwürfe", settings.draft_dir),
        ("Bilder", settings.media_dir),
    ]
    for name, pfad in eintraege:
        table.add_row(name, str(pfad), "ja" if Path(pfad).exists() else "noch nicht")

    console.print(table)
    if not ENV_PATH.exists():
        console.print("\n[yellow]Die .env fehlt noch. Leg sie an mit:[/yellow] [bold]insta-agent setup[/bold]")


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
