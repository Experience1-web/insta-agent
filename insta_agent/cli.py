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


JA_WOERTER = {"j", "ja", "y", "yes"}
NEIN_WOERTER = {"n", "nein", "no", ""}


def _bestaetigt(frage: str) -> bool:
    """Fragt nach - und versteht sowohl j als auch y.

    `typer.confirm` akzeptiert nur die englischen Wörter. Wer auf einem
    deutschen Rechner sitzt, tippt aber j, bekommt eine englische
    Fehlermeldung und weiß nicht, was er falsch gemacht hat.
    """
    while True:
        antwort = typer.prompt(f"{frage} [j/n]", default="n", show_default=False)
        wort = antwort.strip().lower()
        if wort in JA_WOERTER:
            return True
        if wort in NEIN_WOERTER:
            return False
        console.print("[yellow]Bitte j für ja oder n für nein.[/yellow]")


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
    # Anführungszeichen kommen mit, wenn beim Markieren ein Zeichen zu viel
    # erwischt wird. Ein API-Schlüssel enthält nie welche.
    key = "".join(roh.split()).strip("\"'")
    if key != roh.strip():
        console.print("[dim]Leerraum und Anführungszeichen aus der Eingabe entfernt.[/dim]")

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
def web(
    port: int = typer.Option(8765, help="Auf welchem Port die Oberfläche läuft."),
    host: str = typer.Option(
        "127.0.0.1",
        help="0.0.0.0 macht die Seite für Handy und andere Geräte im Netz erreichbar.",
    ),
    read_only: bool = typer.Option(
        False, "--read-only", help="Nur nachsehen, nicht starten. Für den Zugriff von unterwegs."
    ),
    auto_hours: float = typer.Option(
        0,
        "--auto-hours",
        help="Arbeitstakt in Stunden. 24 heißt: einmal täglich von selbst. 0 schaltet ab.",
    ),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Browser automatisch öffnen."
    ),
    config: Path = typer.Option(None),
) -> None:
    """Startet die Oberfläche im Browser - der bequeme Weg.

    Dort siehst du Kasse, Profil, Kurs, Entwürfe samt Bildern und kannst
    den Agenten per Knopfdruck arbeiten lassen. Das Terminal brauchst du
    dann nur noch zum Starten dieses Befehls.
    """
    _setup_logging(False)
    settings = load_settings(config)

    if not settings.anthropic_api_key:
        console.print(
            "[yellow]Noch kein API-Schlüssel hinterlegt. Die Oberfläche startet "
            "trotzdem, arbeiten kann der Agent damit aber nicht.[/yellow]\n"
            "Trag ihn ein mit: [bold]insta-agent setup[/bold]\n"
        )

    from .web import starte_server

    starte_server(
        settings,
        port=port,
        oeffnen=open_browser,
        host=host,
        nur_lesen=read_only,
        auto_stunden=auto_hours,
    )


@app.command()
def autostart(
    ein: bool = typer.Option(None, "--ein/--aus", help="Autostart ein- oder ausschalten."),
    handy: bool = typer.Option(
        False, "--handy", help="Auch im WLAN erreichbar machen, nur zum Nachsehen."
    ),
    arbeitet: float = typer.Option(
        0, "--arbeitet", help="Arbeitstakt in Stunden, etwa 24 für einmal täglich."
    ),
    port: int = typer.Option(8765),
) -> None:
    """Sorgt dafür, dass das Dashboard beim Anmelden von selbst startet.

    Ohne Angabe wird nur der aktuelle Stand gezeigt.
    """
    from . import windows

    if ein is None:
        stand = "eingeschaltet" if windows.ist_eingeschaltet() else "ausgeschaltet"
        console.print(f"Autostart ist [bold]{stand}[/bold].")
        if ordner := windows.autostart_ordner():
            console.print(f"[dim]Ordner: {ordner}[/dim]")
        console.print(
            "\nEinschalten mit [bold]insta-agent autostart --ein[/bold]"
            if not windows.ist_eingeschaltet()
            else "\nAusschalten mit [bold]insta-agent autostart --aus[/bold]"
        )
        return

    ergebnis = (
        windows.einschalten(
            host="0.0.0.0" if handy else "127.0.0.1",
            port=port,
            nur_lesen=handy,
            auto_stunden=arbeitet,
        )
        if ein
        else windows.ausschalten()
    )
    farbe = "green" if ergebnis.erfolg else "red"
    console.print(f"[{farbe}]{ergebnis.nachricht}[/{farbe}]")
    if ergebnis.pfad and ergebnis.erfolg and ein:
        console.print(f"[dim]{ergebnis.pfad}[/dim]")
    if not ergebnis.erfolg:
        raise typer.Exit(1)


@app.command()
def wallet(
    adresse: str = typer.Option("", help="Empfangsadresse. NIEMALS der private Schlüssel."),
    kette: str = typer.Option("base", help="ethereum, base, polygon, solana …"),
    entfernen: bool = typer.Option(False, "--entfernen", help="Adresse wieder löschen."),
    config: Path = typer.Option(None),
) -> None:
    """Hinterlegt eine Adresse, auf der Einnahmen ankommen können.

    Nur die Empfangsadresse. Der Agent bekommt keine Schlüssel und kann
    nichts senden - er liest bei seiner Recherche fremde Webseiten, und
    deren Text landet in seinem Kontext.
    """
    from .config import set_env_value
    from .wallet import maskiere, pruefe_adresse

    settings = load_settings(config)

    if entfernen:
        set_env_value("WALLET_ADDRESS", "")
        console.print("[green]Adresse entfernt.[/green]")
        return

    if not adresse:
        if settings.wallet_address:
            console.print(
                Panel(
                    f"Adresse: [bold]{maskiere(settings.wallet_address)}[/bold]\n"
                    f"Kette:   {settings.wallet_chain or 'nicht angegeben'}\n\n"
                    "[dim]Der Agent kann hierauf nur empfangen, nicht senden.[/dim]",
                    title="Zahlungsweg",
                )
            )
        else:
            console.print("[yellow]Noch kein Zahlungsweg hinterlegt.[/yellow]")
            console.print(
                "Eintragen mit: [bold]insta-agent wallet --adresse 0x… --kette base[/bold]"
            )
        return

    pruefung = pruefe_adresse(adresse, kette)
    if not pruefung.ok:
        console.print(f"[red]{pruefung.grund}[/red]")
        raise typer.Exit(1)

    set_env_value("WALLET_ADDRESS", adresse.strip())
    set_env_value("WALLET_CHAIN", kette.strip())
    console.print(f"[green]Zahlungsweg hinterlegt: {maskiere(adresse.strip())} auf {kette}[/green]")
    console.print(
        "\n[dim]Der Agent bezieht das ab jetzt in seine Geschäftsplanung ein. "
        "Eingegangene Beträge trägst du mit `insta-agent earn` in seine Kasse ein.[/dim]"
    )


@app.command()
def stopp(
    port: int = typer.Option(8765, help="Port, auf dem das Dashboard läuft."),
) -> None:
    """Beendet ein laufendes Dashboard, dessen Fenster nicht mehr auffindbar ist.

    Läuft noch ein altes, kann kein neues starten - und der Browser zeigt
    weiter den alten Stand, ohne dass man den Grund sieht.
    """
    import socket

    from .web import beende_dashboard

    with socket.socket() as pruefung:
        if pruefung.connect_ex(("127.0.0.1", port)) != 0:
            console.print(f"[dim]Auf Port {port} läuft kein Dashboard.[/dim]")
            return

    beendet, meldung = beende_dashboard(port)
    console.print(f"[{'green' if beendet else 'red'}]{meldung}[/]")
    if not beendet:
        raise typer.Exit(1)


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

    if not settings.bild.aktiv:
        table.add_row("Bilder", "[dim]typografisch (insta-agent bilder)[/dim]")
    elif settings.bild.anbieter == "lokal":
        table.add_row("Bilder", f"[green]eigener Rechner[/green] unter {settings.bild.token}")
    else:
        preis = settings.bild.kosten_pro_bild_usd
        table.add_row(
            "Bilder",
            f"[green]{settings.bild.anbieter}[/green] · "
            + (f"{preis:.3f} USD je Bild" if preis > 0 else "kostenloses Kontingent"),
        )

    table.add_row(
        "Freigabe",
        "[green]du entscheidest[/green]"
        if settings.posting.freigabe_noetig
        else "[yellow]Autopilot - er postet ohne Rückfrage[/yellow]",
    )
    table.add_row(
        "Instagram",
        "[green]verbunden[/green]" if settings.instagram_ready else "[dim]nicht nötig für Entwürfe[/dim]",
    )
    if settings.postet_wirklich:
        table.add_row("Veröffentlichen", "[green]scharf - Freigabe geht raus[/green]")
    elif settings.can_publish:
        table.add_row(
            "Veröffentlichen",
            "[yellow]eingerichtet, aber Trockenlauf (insta-agent scharf)[/yellow]",
        )
    else:
        table.add_row("Veröffentlichen", "[dim]nur Entwürfe[/dim]")
    if settings.instagram_ready:
        from .instagram.ablage import baue_ablagen

        # Wo die Bilder liegen, wenn Instagram sie abholt. Mehrere, weil
        # Meta manche Speicher nicht annimmt.
        namen = [a.name for a in baue_ablagen(settings.ablage_anbieter, settings.ablage_token)]
        table.add_row("Bildspeicher", " → ".join(namen) if namen else "[red]keiner[/red]")
    console.print(table)

    if schluessel and schluessel.startswith("sk-ant-") and not kaputt:
        console.print("\n[green]Alles bereit. Starte mit:[/green] [bold]insta-agent run[/bold]")


@app.command()
def kasse(
    guthaben: float = typer.Argument(
        None, help="Was wirklich auf dem Konto ist, in USD. Ohne Angabe wird nur gezeigt."
    ),
    schluessel: bool = typer.Option(
        False, "--schluessel", help="Admin-Schluessel eintragen, damit er selbst nachrechnet."
    ),
    config: Path = typer.Option(None),
) -> None:
    """Zeigt die Kasse und gleicht sie mit dem echten Konto ab.

    Der Agent rechnet mit, was ein Aufruf kosten sollte - aus Tokenzahl
    und Preisliste. Das ist eine Schaetzung. Mit einem Admin-Schluessel
    liest er stattdessen die echte Abrechnung und fuehrt seinen Stand von
    allein nach; ohne ihn traegst du den Stand hier von Hand ein.
    """
    from .config import set_env_value

    if schluessel:
        _admin_schluessel_eintragen(set_env_value)
        return

    agent = _agent(config)
    try:
        vorher = agent.treasury.state()

        if guthaben is None:
            _kasse_zeigen(agent, vorher)
            return

        bereits = _bereits_heute(agent)
        differenz = agent.treasury.setze_anker(guthaben, bereits)
        neu = agent.treasury.state()
        if differenz == 0:
            console.print(f"[green]Stimmt schon:[/green] {neu.balance_usd:.2f} USD.")
        else:
            farbe = "green" if differenz > 0 else "yellow"
            console.print(
                f"Vorher [bold]{vorher.balance_usd:.2f}[/bold], jetzt "
                f"[bold]{neu.balance_usd:.2f} USD[/bold] ([{farbe}]{differenz:+.2f}[/])."
            )
        if bereits is None:
            console.print(
                "\n[dim]Den Stand musst du weiter selbst eintragen. Damit er das"
                " allein kann:\n  insta-agent kasse --schluessel[/dim]"
            )
        else:
            console.print(
                "\n[green]Ab jetzt rechnet er selbst nach.[/green]"
                " Vor jedem Zyklus liest er die echte Abrechnung."
            )
        _modus_hinweis(neu)
    finally:
        agent.close()


def _kasse_zeigen(agent, stand) -> None:
    """Zeigt den Stand - und fuehrt ihn vorher nach, wenn er das kann."""
    if agent.abrechnung is not None and agent.treasury.rechnet_selbst():
        try:
            agent.treasury.aus_abrechnung(agent.abrechnung)
        except Exception as exc:  # noqa: BLE001 - der Grund gehoert auf den Schirm
            console.print(f"[yellow]Abrechnung nicht erreichbar:[/yellow] {exc}")
        else:
            stand = agent.treasury.state()
            console.print("[dim]Aus der echten Abrechnung nachgefuehrt.[/dim]")

    console.print(f"Stand: [bold]{stand.balance_usd:.2f} USD[/bold] ({stand.mode.value}).")
    console.print(
        f"[dim]Ausgegeben {stand.spent_usd:.2f}, selbst verdient {stand.earned_usd:.2f}.[/dim]"
    )
    if not agent.treasury.rechnet_selbst():
        console.print(
            "\n[dim]Er schaetzt. Echten Stand eintragen: insta-agent kasse 1.11\n"
            "Oder ihn selbst nachrechnen lassen: insta-agent kasse --schluessel[/dim]"
        )
    _modus_hinweis(stand)


def _bereits_heute(agent) -> float | None:
    """Was heute vor dem Eintragen schon angefallen ist - None ohne Schluessel.

    Die Abrechnung loest nur ganze Tage auf. Ohne diesen Wert wuerde der
    heutige Verbrauch spaeter ein zweites Mal vom Guthaben abgehen.
    """
    if agent.abrechnung is None:
        return None
    from datetime import datetime, timezone

    try:
        return agent.abrechnung.kosten_seit(datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - kein Grund, den Eintrag zu verlieren
        console.print(f"[yellow]Abrechnung nicht erreichbar:[/yellow] {exc}")
        console.print(
            "[dim]Der Stand wird trotzdem eingetragen. Falls es am Schluessel"
            " liegt:\n  insta-agent kasse --schluessel[/dim]"
        )
        return None


def _modus_hinweis(stand) -> None:
    if stand.mode.value == "frugal":
        console.print(
            "\n[yellow]Sparbetrieb.[/yellow] Er arbeitet weiter, aber mit dem"
            " billigen Modell und ohne Websuche."
        )
    elif stand.mode.value == "halted":
        console.print(
            "\n[red]Zu wenig zum Arbeiten.[/red] Lad Guthaben auf unter"
            " console.anthropic.com."
        )


def _admin_schluessel_eintragen(set_env_value) -> None:
    console.print(
        Panel(
            "Damit er seinen Kontostand selbst nachrechnet, braucht er Lesezugriff\n"
            "auf die Abrechnung.\n\n"
            "[bold]Meistens ist das hier gar nicht noetig:[/bold] Zuerst wird immer\n"
            "der Schluessel versucht, den du schon hast. Darf der es, bist du fertig.\n"
            "Nur wenn er abgewiesen wird, brauchst du einen eigenen.\n\n"
            "[bold]So kommst du daran:[/bold]\n"
            "  1. platform.claude.com/settings/admin-keys oeffnen\n"
            "  2. Create key, Namen vergeben, Create\n"
            "  3. Den Schluessel kopieren (faengt mit sk-ant-admin01 an)\n"
            "     Er wird nur ein einziges Mal angezeigt.\n\n"
            "[yellow]Wichtig zu wissen:[/yellow] Dieser Schluessel kann mehr als\n"
            "lesen - er darf auch API-Schluessel anlegen und widerrufen. Der Agent\n"
            "bekommt ihn nie zu sehen: Er wird nur fuer diesen einen Abruf benutzt\n"
            "und gerät in keinen Prompt. Wenn dir das zu viel ist, lass es - dann\n"
            "traegst du den Stand weiter von Hand ein.\n\n"
            "[dim]Einzelkonten haben keinen Zugang zu dieser Schnittstelle. Falls\n"
            "die Probe fehlschlaegt, ist das der Grund - dann bleibt es beim\n"
            "Eintragen von Hand.[/dim]",
            title="Kontostand selbst nachrechnen",
        )
    )

    token = _frag_schluessel("Admin-Schluessel")
    if not token.startswith("sk-ant-admin"):
        console.print(
            "[yellow]Admin-Schluessel fangen mit 'sk-ant-admin' an. Deiner nicht -"
            " vermutlich ist das der normale API-Schluessel.[/yellow]"
        )
        if not _bestaetigt("Trotzdem eintragen?"):
            raise typer.Exit(1)

    console.print("\n[dim]Probe: rufe die Abrechnung ab ...[/dim]")
    from datetime import datetime, timezone

    from .economy.abrechnung import Abrechnung, Abrechnungsfehler

    probe = Abrechnung(token)
    try:
        kosten = probe.kosten_seit(datetime.now(timezone.utc))
    except Abrechnungsfehler as exc:
        console.print(f"[red]Geht nicht:[/red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        probe.close()

    set_env_value("ANTHROPIC_ADMIN_KEY", token)
    console.print(
        f"[green]Probe bestanden.[/green] Heute abgerechnet: {kosten:.2f} USD.\n\n"
        "Jetzt noch einmal den echten Stand eintragen, dann rechnet er ab da\n"
        "allein weiter:\n  [bold]insta-agent kasse 1.11[/bold]"
    )


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
def bilder(
    config: Path = typer.Option(None),
    loeschen: bool = typer.Option(False, "--loeschen", help="Bilderzeugung wieder abschalten"),
) -> None:
    """Richtet ein, wer die Bilder malt.

    Claude erzeugt keine Bilder. Ohne diese Einrichtung bleibt es bei der
    typografischen Fassung.
    """
    from .config import set_env_value

    if loeschen:
        set_env_value("BILD_ANBIETER", "")
        set_env_value("BILD_TOKEN", "")
        console.print("[green]Abgeschaltet.[/green] Es bleibt bei der Typografie.")
        return

    # Was schon hinterlegt ist, zuerst. Sonst tippt man einen Schluessel
    # noch einmal ein, den man laengst eingetragen hat - und weiss nach
    # dem dritten Anbieterwechsel nicht mehr, welcher gerade gilt.
    _zeige_bildstand(config)

    console.print(
        Panel(
            "Der Agent schreibt die Bildbeschreibung selbst. Malen lassen muss\n"
            "er sie woanders - Claude kann das nicht.\n\n"
            "[bold]1  Pollinations[/bold]  [green]kostenlos, nichts einzurichten[/green]\n"
            "   FLUX ohne Konto und ohne Schluessel. Sofort einsatzbereit.\n"
            "   [dim]Ohne kostenloses Konto kann ein Wasserzeichen im Bild\n"
            "   landen, und ein Dienst ohne Anmeldung gibt keine Zusagen -\n"
            "   bei Ueberlastung bleibt es bei der Typografie.[/dim]\n\n"
            "[bold]2  Cloudflare[/bold]  [green]rund 170 Bilder am Tag frei[/green]\n"
            "   FLUX.1 schnell. Braucht ein kostenloses Cloudflare-Konto,\n"
            "   Kontonummer und einen Schluessel mit dem Recht 'Workers AI'.\n"
            "   Setzt sich jede Nacht zurueck.\n\n"
            "[bold]3  Google Gemini[/bold]  [green]kostenlos moeglich[/green]\n"
            "   Schluessel auf aistudio.google.com, ohne Zahlungsdaten.\n"
            "   Knappes Freikontingent pro Tag.\n\n"
            "[bold]4  Eigener Rechner[/bold]  [green]dauerhaft kostenlos[/green]\n"
            "   Braucht eine NVIDIA-Karte und ein laufendes Bildprogramm\n"
            "   (AUTOMATIC1111, Forge, SD.Next) mit --api. Ab 4 GB mit\n"
            "   SD 1.5, ab 8 GB auch SDXL. Einmal aufbauen, danach keine\n"
            "   Grenzen - aber der Aufbau ist der muehsamste von allen.\n\n"
            "[bold]5  Replicate[/bold]  wenige Cent je Bild\n"
            "   Kein Aufbau, keine Grenzen, beste Qualitaet.\n\n"
            "[bold]6  Leonardo.ai[/bold]  [green]5 USD Startguthaben[/green]\n"
            "   FLUX und Phoenix. Neue Zugaenge bekommen 5 USD, die nicht\n"
            "   verfallen - etwa hundert Bilder, deutlich besser als Gemini.\n"
            "   [dim]Achtung: Die 150 Freitoken am Tag gelten fuer die Webseite,\n"
            "   nicht fuer die Schnittstelle. Automatisch geht nur ueber einen\n"
            "   Produktionsschluessel, und der rechnet ab.[/dim]",
            title="Wer malt die Bilder?",
        )
    )

    wahl = typer.prompt("Welcher Weg? [1/2/3/4/5/6]", default="1").strip()[:1]

    if wahl == "4":
        console.print(
            "\n[dim]Das Bildprogramm muss laufen und mit --api gestartet sein.\n\n"
            "In [bold]Stability Matrix[/bold]: auf das Zahnrad neben 'Launch',\n"
            "dann unten bei 'Extra Launch Arguments' eintragen:\n"
            "  [bold]--api --medvram --xformers[/bold]\n"
            "(Hat die Karte 8 GB oder mehr und laeuft ein XL-Modell, statt\n"
            "--medvram besser --medvram-sdxl.)\n\n"
            "Bei Forge oder AUTOMATIC1111 von Hand: in webui-user.bat in die\n"
            "Zeile COMMANDLINE_ARGS.[/dim]\n"
        )
        adresse = typer.prompt(
            "Adresse des Bildprogramms", default="http://127.0.0.1:7860"
        ).strip().rstrip("/")

        # Sofort nachsehen, ob dort wirklich etwas antwortet. Sonst faellt
        # es erst beim ersten Beitrag auf - und dann sieht es aus, als
        # laege es am Agenten.
        from .imaging.generator import Bildfehler, frage_lokal_ab, modellart

        console.print("\n[dim]Probe: frage das Bildprogramm ...[/dim]")
        try:
            modelle, geladen, auf_karte = frage_lokal_ab(adresse)
        except Bildfehler as exc:
            console.print(f"\n[red]Das hat nicht geklappt.[/red]\n{exc}")
            if not _bestaetigt("Trotzdem so eintragen?"):
                raise typer.Exit(1) from None
            modelle, geladen, auf_karte = [], "", None
        else:
            rechner = {
                True: "[green]Grafikkarte[/green]",
                False: "[red]nur Prozessor[/red]",
                None: "[dim]nicht feststellbar[/dim]",
            }[auf_karte]
            console.print(
                Panel(
                    f"Gefunden: {len(modelle)} Modell(e)\n"
                    f"Geladen:  {geladen or 'keines'}\n"
                    f"Rechnet:  {rechner}",
                    title="[green]Verbindung steht[/green]",
                )
            )
            if auf_karte is False:
                console.print(
                    Panel(
                        "Das Bildprogramm benutzt deine Grafikkarte nicht, sondern\n"
                        "den Prozessor. Ein Bild dauert damit nicht eine Minute,\n"
                        "sondern zwanzig bis dreissig - fuer einen Account, der\n"
                        "taeglich postet, ist das unbrauchbar.\n\n"
                        "Ursache ist fast immer PyTorch in der Prozessorfassung\n"
                        "(im Protokoll steht dann 'Torch not compiled with CUDA\n"
                        "enabled' oder eine Fassung mit '+cpu').\n\n"
                        "In Stability Matrix: beim Paket auf die drei Punkte, dann\n"
                        "'Reinstall' - und bei der Frage nach der Hardware NVIDIA\n"
                        "auswaehlen, nicht CPU.",
                        title="[red]Achtung: laeuft ohne Grafikkarte[/red]",
                    )
                )
            for i, name in enumerate(modelle[:12], 1):
                console.print(f"  {i:2}  {name}")
            if len(modelle) > 12:
                console.print(f"  [dim]... und {len(modelle) - 12} weitere[/dim]")

        modell = typer.prompt(
            "\nName oder Nummer des Modells (leer lassen fuer das geladene)", default=""
        ).strip()
        if modell.isdigit() and modelle and 1 <= int(modell) <= len(modelle):
            modell = modelle[int(modell) - 1]

        set_env_value("BILD_ANBIETER", "lokal")
        set_env_value("BILD_TOKEN", adresse)
        set_env_value("BILD_KOSTEN", "0")
        set_env_value("BILD_MODELL", modell)

        # Die Bauart entscheidet ueber Masze, CFG und Sampler. Erkannt wird
        # sie am Namen, und das kann danebengehen - deshalb wird sie
        # gezeigt und darf berichtigt werden, statt still zu gelten.
        art = modellart(modell or geladen)
        erklaerung = {
            "flux": "FLUX: ohne Negativfuehrung, CFG 1, 20 Schritte.",
            "sdxl": "SDXL: CFG 5, 28 Schritte, gemalt auf 792x1408.",
            "sd15": (
                "SD 1.5: CFG 7, 30 Schritte, gemalt auf 512x768 und danach\n"
                "vom Bildprogramm selbst auf 1024x1536 hochgerechnet."
            ),
        }
        console.print(f"\n[dim]Erkannt als [bold]{art}[/bold] - {erklaerung[art]}[/dim]")
        if _bestaetigt("Ist das falsch? Dann von Hand festlegen"):
            gewaehlt = typer.prompt(
                "Bauart eintippen (flux / sdxl / sd15)", default=art
            ).strip().casefold()
            if gewaehlt in erklaerung:
                art = gewaehlt
                console.print(f"[dim]Gut: {erklaerung[art]}[/dim]")
        set_env_value("BILD_ART", art)
        console.print(
            "\n[green]Eingetragen.[/green] Lass das Bildprogramm laufen, wenn der "
            "Agent arbeitet."
        )
        _bild_fertig()
        return

    if wahl == "5":
        token = _frag_schluessel(
            "Schluessel von replicate.com", behalten=_alter_schluessel(config, "replicate")
        )
        set_env_value("BILD_ANBIETER", "replicate")
        set_env_value("BILD_TOKEN", token)
        set_env_value("BILD_MODELL", "black-forest-labs/flux-1.1-pro")
        preis = typer.prompt("Kosten pro Bild in USD (steht auf der Preisseite)", default="0.04")
        try:
            float(preis)
        except ValueError:
            console.print("[yellow]Keine Zahl - Voreinstellung bleibt.[/yellow]")
        else:
            set_env_value("BILD_KOSTEN", preis)
        _bild_fertig()
        return

    if wahl == "6":
        console.print(
            "\n[dim]Den Schluessel bekommst du unter app.leonardo.ai ->\n"
            "User Settings -> API Access -> Create New Key. Beim ersten Mal\n"
            "musst du die Produktions-Schnittstelle freischalten; das\n"
            "Startguthaben von 5 USD ist dann schon drauf.[/dim]\n"
        )
        token = _frag_schluessel(
            "Schluessel von leonardo.ai", behalten=_alter_schluessel(config, "leonardo")
        )
        set_env_value("BILD_ANBIETER", "leonardo")
        set_env_value("BILD_TOKEN", token)
        modell = typer.prompt(
            "Modell-Kennung (UUID, leer lassen fuer Phoenix)", default=""
        ).strip()
        set_env_value("BILD_MODELL", modell)
        preis = typer.prompt("Kosten pro Bild in USD (grob)", default="0.02")
        try:
            float(preis)
        except ValueError:
            console.print("[yellow]Keine Zahl - Voreinstellung bleibt.[/yellow]")
        else:
            set_env_value("BILD_KOSTEN", preis)
        _bild_fertig()
        return

    if wahl == "2":
        console.print(
            "\n[dim]Beides steht im Cloudflare-Dashboard:\n"
            "  Kontonummer: rechts in der Seitenleiste unter 'Account ID'\n"
            "  Schluessel:  Mein Profil -> API-Tokens -> Token erstellen,\n"
            "               Recht 'Workers AI' -> Read[/dim]\n"
        )
        konto = typer.prompt("Kontonummer (Account ID)").strip()
        schluessel = _frag_schluessel("Zugriffsschluessel")
        set_env_value("BILD_ANBIETER", "cloudflare")
        # Beide Angaben in einer Einstellung: eine Stelle weniger, an der
        # man sich vertun kann.
        set_env_value("BILD_TOKEN", f"{konto}:{schluessel}")
        set_env_value("BILD_MODELL", "")
        set_env_value("BILD_KOSTEN", "0")
        _bild_fertig()
        return

    if wahl == "3":
        token = _frag_schluessel(
            "Schluessel von aistudio.google.com", behalten=_alter_schluessel(config, "gemini")
        )
        set_env_value("BILD_ANBIETER", "gemini")
        set_env_value("BILD_TOKEN", token)
        set_env_value("BILD_MODELL", "gemini-2.5-flash-image")
        set_env_value("BILD_KOSTEN", "0")
        console.print(
            "\n[dim]Falls du dort spaeter Zahlungsdaten hinterlegst, trag die Kosten\n"
            "pro Bild mit `insta-agent bilder` neu ein - sonst rechnet er mit null.[/dim]"
        )
        _bild_fertig()
        return

    # Weg 1: Pollinations. Nichts einzurichten - deshalb die Voreinstellung.
    console.print(
        "\n[dim]Pollinations braucht keinen Schluessel. Wenn du auf\n"
        "auth.pollinations.ai einen kostenlosen Zugang anlegst, faellt das\n"
        "Wasserzeichen weg - sonst einfach leer lassen.[/dim]\n"
    )
    token = _frag_schluessel("Schluessel von Pollinations (oder leer lassen)", noetig=False)
    set_env_value("BILD_ANBIETER", "pollinations")
    set_env_value("BILD_TOKEN", token)
    set_env_value("BILD_MODELL", "flux")
    set_env_value("BILD_KOSTEN", "0")
    _bild_fertig()


def _verkuerzt(token: str) -> str:
    """Genug zum Wiedererkennen, zu wenig zum Missbrauchen."""
    sauber = (token or "").strip()
    if not sauber:
        return ""
    return f"...{sauber[-4:]}" if len(sauber) > 8 else "(kurz)"


# Wie die Anbieter im Klartext heissen.
ANBIETERNAMEN = {
    "pollinations": "Pollinations",
    "cloudflare": "Cloudflare",
    "gemini": "Google Gemini",
    "lokal": "Eigener Rechner",
    "replicate": "Replicate",
    "leonardo": "Leonardo.ai",
}


def _alter_schluessel(config: Path | None, anbieter: str) -> str:
    """Der hinterlegte Schluessel - aber nur, wenn es derselbe Anbieter ist.

    Ein Cloudflare-Schluessel taugt nicht fuer Gemini, und ihn dort als
    "hinterlegt" anzubieten waere schlimmer als gar keine Hilfe.
    """
    try:
        einst = load_settings(config)
    except Exception:  # noqa: BLE001
        return ""
    if (einst.bild.anbieter or "").strip() != anbieter:
        return ""
    return (einst.bild.token or "").strip()


def _zeige_bildstand(config: Path | None) -> None:
    """Sagt, wer gerade malt und ob ein Schluessel hinterlegt ist."""
    try:
        einst = load_settings(config)
    except Exception:  # noqa: BLE001 - ohne Einstellungen fangen wir bei null an
        return

    anbieter = (einst.bild.anbieter or "").strip()
    if not anbieter:
        console.print("[dim]Bisher ist kein Bilddienst eingerichtet.[/dim]\n")
        return

    name = ANBIETERNAMEN.get(anbieter, anbieter)
    token = (einst.bild.token or "").strip()
    zeilen = [f"Eingerichtet: [bold]{name}[/bold]"]
    if anbieter == "lokal":
        zeilen.append(f"Adresse:      {token or 'keine'}")
    elif token:
        zeilen.append(f"Schluessel:   hinterlegt ({_verkuerzt(token)})")
    else:
        zeilen.append("Schluessel:   keiner noetig")
    if modell := (einst.bild.modell or "").strip():
        zeilen.append(f"Modell:       {modell}")

    console.print(Panel("\n".join(zeilen), title="Stand jetzt"))
    console.print(
        "[dim]Wenn du beim selben Anbieter bleibst, kannst du den Schluessel\n"
        "leer lassen - der hinterlegte bleibt dann stehen.[/dim]\n"
    )


def _frag_schluessel(frage: str, *, noetig: bool = True, behalten: str = "") -> str:
    """Fragt einen Schluessel ab und raeumt Einfuege-Unfaelle weg.

    `behalten` ist ein schon hinterlegter Schluessel: Dann darf die
    Eingabe leer bleiben und der alte gilt weiter. Niemand soll denselben
    Schluessel zweimal eintippen muessen, nur weil er den Anbieter noch
    einmal bestaetigt.
    """
    if behalten:
        console.print(f"[dim]Hinterlegt: {_verkuerzt(behalten)} - Enter behaelt ihn.[/dim]")
        roh = typer.prompt(frage, hide_input=True, default="")
        token = "".join(roh.split()).strip("\"'")
        return token or behalten
    return _frag_schluessel_roh(frage, noetig=noetig)


def _frag_schluessel_roh(frage: str, *, noetig: bool = True) -> str:
    """Fragt einen Schluessel ab und raeumt Einfuege-Unfaelle weg.

    `noetig=False` laesst eine leere Eingabe zu - fuer Schluessel, ohne die
    es auch geht. Dann wird ein leerer Text zurueckgegeben.
    """
    roh = typer.prompt(frage, hide_input=True, default="" if not noetig else None)
    # Mehrzeiliges Einfuegen zerlegt den Schluessel sonst still.
    token = "".join(roh.split()).strip("\"'")
    if not token and noetig:
        console.print("[yellow]Nichts eingetragen.[/yellow]")
        raise typer.Exit(1)
    return token


def _bild_fertig() -> None:
    console.print(
        "\n[green]Eingetragen.[/green] Ab dem naechsten Zyklus malt er seine "
        "Bilder selbst.\n[dim]Pruefen: insta-agent check[/dim]"
    )


@app.command()
def posten(config: Path = typer.Option(None)) -> None:
    """Schickt raus, was schon freigegeben ist - ohne Denkzyklus.

    Kostet kein Guthaben: Es wird nichts geschrieben und nichts gedacht,
    nur hochgeladen.
    """
    from .web import version

    # Ohne diese Zeile sieht man einem Fehlschlag nicht an, ob die neue
    # Fassung ueberhaupt angekommen ist.
    console.print(f"[dim]Stand {version()}[/dim]")

    settings = load_settings(config)
    if not settings.postet_wirklich:
        if not settings.can_publish:
            console.print(
                "[red]Es fehlt der Zugang.[/red]\n"
                "  insta-agent instagram\n"
                "  insta-agent ablage"
            )
        else:
            console.print(
                "[yellow]Noch im Trockenlauf.[/yellow] Erst scharf schalten:\n"
                "  insta-agent scharf"
            )
        raise typer.Exit(1)

    agent = _agent(config)
    try:
        offen = agent.store.approved_drafts(limit=20)
        if not offen:
            console.print("[dim]Nichts freigegeben - es gibt nichts zu senden.[/dim]")
            return

        console.print(f"[dim]{len(offen)} freigegeben. Schicke raus ...[/dim]\n")
        bericht = agent.veroeffentliche_jetzt()
        for schritt in bericht.steps:
            console.print(f"  {schritt}")

        if bericht.published_media_ids:
            console.print(
                f"\n[green]{len(bericht.published_media_ids)} veroeffentlicht.[/green]"
            )
        else:
            console.print("\n[yellow]Nichts ging raus.[/yellow] Die Gruende stehen oben.")
    finally:
        agent.close()


@app.command()
def scharf(
    config: Path = typer.Option(None),
    aus: bool = typer.Option(False, "--aus", help="Wieder auf Trockenlauf stellen"),
) -> None:
    """Schaltet das wirkliche Veroeffentlichen ein oder aus.

    Solange dieser Schalter aus ist, macht der Agent einen Trockenlauf:
    Er legt Entwuerfe ab, statt sie hinauszuschicken. Das ist die
    Hauptsicherung - sie muss einmal bewusst umgelegt werden.
    """
    from .config import set_env_value

    if aus:
        set_env_value("POSTING_LIVE", "false")
        console.print(
            "[green]Trockenlauf.[/green] Er legt jetzt wieder nur Entwuerfe ab."
        )
        return

    settings = load_settings(config)
    if not settings.can_publish:
        console.print(
            "[red]Noch nicht moeglich.[/red] Es fehlt der Instagram-Zugang oder "
            "der Platz fuer die Bilder.\n"
            "  insta-agent instagram\n"
            "  insta-agent ablage"
        )
        raise typer.Exit(1)

    console.print(
        Panel(
            "Ab jetzt geht jeder Beitrag, den du freigibst, wirklich auf\n"
            "Instagram - unter deinem Kontonamen, oeffentlich sichtbar.\n\n"
            "[dim]Freigeben bleibt dein Knopf. Ohne dein Ja passiert nichts.[/dim]",
            title="Wirklich veroeffentlichen",
        )
    )
    if not _bestaetigt("Einschalten?"):
        console.print("Abgebrochen. Es bleibt beim Trockenlauf.")
        raise typer.Exit(0)

    set_env_value("POSTING_LIVE", "true")
    console.print(
        "\n[green]Eingeschaltet.[/green] Freigeben heisst ab jetzt: es geht raus."
    )


@app.command()
def ablage(
    config: Path = typer.Option(None),
    loeschen: bool = typer.Option(False, "--loeschen"),
) -> None:
    """Richtet den Platz ein, von dem Instagram die Bilder abholt.

    Instagram nimmt keine Datei entgegen - es bekommt eine Adresse und
    holt sich das Bild selbst. Dein Rechner ist von aussen nicht
    erreichbar, also muss das Bild kurz irgendwo im Netz liegen.
    """
    from .config import set_env_value

    if loeschen:
        set_env_value("ABLAGE_TOKEN", "")
        console.print(
            "[green]Entfernt.[/green] Veroeffentlichen geht weiter - ueber die"
            " Speicher ohne Konto."
        )
        return

    console.print(
        Panel(
            "Instagram laedt kein Bild hoch, das du ihm gibst. Es bekommt eine\n"
            "Adresse im Netz und holt sich das Bild dort ab.\n\n"
            "[bold]Normalerweise ist hier nichts zu tun.[/bold] Der Agent nutzt\n"
            "Bildspeicher, die weder Konto noch Schluessel brauchen, und\n"
            "probiert der Reihe nach den naechsten, wenn Instagram eine\n"
            "Adresse nicht annimmt.\n\n"
            "Ein Schluessel von imgbb ist nur eine zusaetzliche Rueckfallebene.\n"
            "  1. imgbb.com oeffnen, kostenlos anmelden\n"
            "  2. api.imgbb.com aufrufen -> 'Get API key'\n"
            "  3. Den Schluessel kopieren\n\n"
            "[dim]Leer lassen und Enter druecken geht auch - dann bleibt es bei\n"
            "den Speichern ohne Konto.[/dim]",
            title="Platz fuer die Bilder",
        )
    )

    token = _frag_schluessel("Schluessel von imgbb (oder leer lassen)", noetig=False)
    if not token.strip():
        console.print(
            "\n[green]Nichts noetig.[/green] Die Speicher ohne Konto sind schon"
            " eingestellt."
        )
        return
    set_env_value("ABLAGE_TOKEN", token)
    console.print(
        "\n[green]Eingetragen.[/green] Er hat jetzt einen Speicher mehr zur Auswahl."
        "\n[dim]Pruefen: insta-agent check[/dim]"
    )


@app.command()
def rechte(config: Path = typer.Option(None)) -> None:
    """Zeigt, welche Instagram-Berechtigungen der hinterlegte Zugang hat.

    Damit lässt sich nachsehen, ob eine nachgeholte Berechtigung
    angekommen ist - ohne die ganze Einrichtung noch einmal zu
    durchlaufen.
    """
    from .instagram.einrichten import GLEICHWERTIG, NOETIGE_RECHTE, pruefe_rechte

    einst = load_settings(config)
    if not (einst.ig_access_token and einst.meta_app_id and einst.meta_app_secret):
        console.print(
            "[yellow]Noch kein Instagram-Zugang hinterlegt.[/yellow]\n"
            "Richte ihn zuerst ein: Doppelklick auf  11 - Instagram verbinden"
        )
        raise typer.Exit(1)

    erteilt, grund = pruefe_rechte(
        einst.ig_access_token, einst.meta_app_id, einst.meta_app_secret
    )
    if grund:
        console.print(f"[red]{grund}[/red]")
        raise typer.Exit(1)

    zeilen = []
    fehlt = []
    for recht, wozu in NOETIGE_RECHTE.items():
        da = recht in erteilt or set(erteilt) & set(GLEICHWERTIG.get(recht, ()))
        zeilen.append(f"{'[green]ja [/green]' if da else '[red]NEIN[/red]'}  {recht}  -  {wozu}")
        if not da:
            fehlt.append(recht)

    console.print(Panel("\n".join(zeilen), title="Was der Zugang darf"))
    if fehlt:
        console.print(
            "\n[yellow]Es fehlt etwas.[/yellow] Wenn die Berechtigung im "
            "Graph-API-Explorer\nbeim Tippen gar nicht vorgeschlagen wird, ist "
            "sie fuer deine App\nnoch nicht freigeschaltet:\n\n"
            "  developers.facebook.com -> deine App\n"
            "  -> linkes Menue 'App-Ueberpruefung'\n"
            "  -> 'Berechtigungen und Funktionen'\n"
            "  -> oben ins Suchfeld den Namen eintippen\n"
            "  -> rechts auf 'Standardzugriff anfordern' klicken\n\n"
            "Danach taucht sie im Explorer auf."
        )
    else:
        console.print("\n[green]Alles da. Er sieht seine Zahlen.[/green]")


@app.command()
def instagram(config: Path = typer.Option(None)) -> None:
    """Richtet den Instagram-Zugang ein, damit der Agent selbst posten kann.

    Du brauchst drei Angaben von developers.facebook.com. Den Rest -
    langlebiger Token, Seite finden, Konto-Nummer holen - macht dieser
    Befehl.
    """
    from .config import set_env_value
    from .instagram.einrichten import Einrichtungsfehler, richte_ein

    console.print(
        Panel(
            "Du brauchst drei Angaben aus deiner Meta-App.\n\n"
            "[bold]App-ID und App-Geheimnis[/bold]\n"
            "  developers.facebook.com -> deine App -> Einstellungen -> Allgemein\n\n"
            "[bold]Zugriffsschluessel[/bold]\n"
            "  developers.facebook.com/tools/explorer\n"
            "  1. Oben rechts bei 'Meta App' deine App waehlen\n"
            "  2. Darunter bei 'User or Page': [bold]User Token[/bold]\n"
            "  3. Unter [bold]Permissions[/bold] ins Feld\n"
            "     [bold]'Berechtigung hinzufuegen'[/bold] klicken und den Namen\n"
            "     tippen - die Liste darunter ist scrollbar und zeigt\n"
            "     nicht alles. Diese fuenf brauchst du:\n"
            "       instagram_basic\n"
            "       instagram_content_publish\n"
            "       instagram_manage_insights\n"
            "       pages_show_list\n"
            "       pages_read_engagement\n"
            "  4. 'Generate Access Token' druecken\n"
            "  5. Im Fenster von Facebook [bold]alles erlauben[/bold] und die\n"
            "     Seite mit dem Instagram-Konto ankreuzen\n"
            "  6. Den langen Text oben kopieren\n\n"
            "[dim]instagram_manage_insights ist die, ohne die es keine\n"
            "Reichweite und keine Speicherungen gibt - dann lernt er nichts\n"
            "aus seinen eigenen Beitraegen.[/dim]\n\n"
            "[yellow]Dieser Schluessel haelt nur ein bis zwei Stunden.[/yellow]\n"
            "Mach den Rest gleich danach - ich tausche ihn hier gegen einen\n"
            "dauerhaften.",
            title="Instagram-Zugang einrichten",
        )
    )

    app_id = typer.prompt("App-ID").strip()

    # Die Adresse erst jetzt nennen, dafuer vollstaendig: Ohne die
    # App-Nummer laesst sie sich nicht hinschreiben, und "geh in die
    # Einstellungen" ist bei Metas Menue keine Wegbeschreibung.
    console.print(
        f"\n[dim]Das App-Geheimnis steht hier - Adresse kopieren und oeffnen:[/dim]\n"
        f"[bold]https://developers.facebook.com/apps/{app_id}/settings/basic/[/bold]\n"
        "[dim]Dort in der Zeile 'App-Geheimnis' auf  Anzeigen  klicken.\n"
        "Facebook fragt dann nach deinem Passwort.[/dim]"
    )
    app_secret = _frag_schluessel("App-Geheimnis")
    kurzer = _frag_schluessel("Zugriffsschluessel aus dem Explorer")

    console.print("\n[dim]Frage bei Meta nach ...[/dim]")
    try:
        zugang = richte_ein(kurzer, app_id, app_secret)
    except Einrichtungsfehler as exc:
        console.print(f"\n[red]Das hat nicht geklappt.[/red]\n{exc}")
        raise typer.Exit(1) from None

    set_env_value("IG_USER_ID", zugang.ig_user_id)
    set_env_value("IG_ACCESS_TOKEN", zugang.seiten_token)
    set_env_value("META_APP_ID", app_id)
    set_env_value("META_APP_SECRET", app_secret)

    console.print(
        Panel(
            f"Seite:     {zugang.seiten_name}\n"
            f"Konto:     @{zugang.handle}\n"
            f"Follower:  {zugang.follower}\n"
            f"Nummer:    {zugang.ig_user_id}",
            title="[green]Verbunden[/green]",
        )
    )
    if fehlend := zugang.fehlend:
        from .instagram.einrichten import NOETIGE_RECHTE

        console.print(
            Panel(
                "Diese Berechtigungen hat der Schluessel [bold]nicht[/bold]:\n\n"
                + "\n".join(f"  {r}  -  {NOETIGE_RECHTE[r]}" for r in fehlend)
                + "\n\nMeta beschwert sich darueber nicht - es liefert die Felder\n"
                "einfach nicht. Du merkst es sonst erst an leeren Kennzahlen.\n\n"
                "So holst du sie nach:\n"
                "  developers.facebook.com/tools/explorer\n"
                "  App waehlen, bei 'Permissions' den fehlenden Namen ins\n"
                "  Suchfeld tippen, Haken setzen, 'Generate Access Token',\n"
                "  im Facebook-Fenster alles erlauben - und diesen Befehl\n"
                "  noch einmal laufen lassen.",
                title="[yellow]Achtung: es fehlt etwas[/yellow]",
            )
        )
    else:
        console.print("\n[green]Alle noetigen Berechtigungen sind da.[/green]")

    console.print(
        "\n[dim]Es fehlt noch ein oeffentlicher Platz fuer die Bilder -\n"
        "Instagram holt sie sich von einer Adresse im Netz.[/dim]"
    )


def _eignung(verhaeltnis: float) -> str:
    """Was die Form dieses Bildes fuer einen Beitrag bedeutet.

    Die Zahl allein sagt niemandem etwas. "0,45" heisst: eine hochkant
    gescannte Tafel, aus der ein Beitragsbild einen Streifen macht.
    """
    if verhaeltnis >= 2.2:
        return "sehr gut - daraus wird ein Karussell zum Durchwandern"
    if verhaeltnis >= 1.6:
        return "gut - Querformat, wird beschnitten"
    if verhaeltnis >= 0.6:
        return "sehr gut - nahe am Beitragsformat"
    if verhaeltnis >= 0.5:
        return "brauchbar - hochkant wie eine Story"
    return "schlecht - zu hoch, davon sieht man nur einen Streifen"


@app.command()
def bildsuche(
    suchwort: str = typer.Argument(..., help="Wonach gesucht wird, am besten englisch"),
    config: Path = typer.Option(None),
    alle: bool = typer.Option(False, "--alle", help="Jeden Anlauf einzeln zeigen"),
    ansehen: bool = typer.Option(
        False,
        "--ansehen",
        help="Jedes Bild kurz ansehen lassen - kostet rund 0,05 Cent je Bild",
    ),
) -> None:
    """Sucht eine echte freie Aufnahme - und kostet dabei nichts.

    Der ganze Weg ohne einen einzigen Modellaufruf: Wikimedia Commons,
    dann Openverse, Lizenzpruefung, Herunterladen. Damit laesst sich
    nachsehen, ob die Bildsuche bei einem Thema ueberhaupt etwas findet,
    bevor ein Zyklus dafuer Geld ausgibt.

    Gedacht zum Ausprobieren: Wer wissen will, ob "roman coin hoard"
    besser traegt als "Muenzfund", probiert hier beides und sieht in
    zwei Sekunden, was herauskommt.
    """
    from .imaging.echtbild import finde_und_hole, suchbegriffe
    from .imaging.panorama import ist_panorama, stueckzahl

    settings = load_settings(config)
    ziel_ordner = settings.media_dir
    ziel_ordner.mkdir(parents=True, exist_ok=True)

    versuche = suchbegriffe(suchwort)
    console.print(
        Panel(
            f"Gesucht wird nach: [bold]{suchwort}[/bold]\n\n"
            "Anläufe, vom Genauen zum Allgemeinen:\n"
            + "\n".join(f"  {i}. {b}" for i, b in enumerate(versuche, 1))
            + "\n\n[dim]Quellen: Wikimedia Commons, dann Openverse.\n"
            "Kostet nichts - hier wird kein Modell gefragt.[/dim]",
            title="Bildsuche",
        )
    )

    if alle:
        import httpx as _httpx

        from .imaging.echtbild import Bilanz, _frage_commons, _frage_openverse

        with _httpx.Client(timeout=20.0, follow_redirects=True) as client:
            for begriff in versuche:
                bc, bo = Bilanz(), Bilanz()
                _frage_commons(begriff, client, 12, bc)
                _frage_openverse(begriff, client, 12, bo)
                console.print(f"  [bold]{begriff}[/bold]")
                console.print(f"      Commons:   {bc}")
                console.print(f"      Openverse: {bo}")

    console.print("\n[dim]Suche läuft ...[/dim]")

    # Genau derselbe Weg wie im Zyklus, einschliesslich der Fotopruefung.
    # Vorher rief die Probe die Suche direkt auf und ging daran vorbei -
    # dann zeigt sie ein Bild, das der Agent gar nicht genommen haette.
    ziel = ziel_ordner / "suchprobe.jpg"
    verworfen: list[tuple[str, str]] = []

    def mitschreiben(bild, taugte: bool, grund: str) -> None:
        if not taugte:
            verworfen.append((bild.seite, grund))

    hinsehen = None
    if ansehen:
        from .economy import Treasury
        from .llm import Brain
        from .store import Store

        gehirn = Brain(
            settings.llm, Treasury(Store(settings.db_path), settings.economy)
        )
        console.print(
            "[dim]Jedes Bild wird kurz angesehen. Das kostet rund 0,05 Cent"
            " je Bild - bei vier Bildern also ein Fünftel Cent.[/dim]\n"
        )

        def hinsehen(pfad):  # noqa: F811 - bewusst erst hier definiert
            return gehirn.beurteile_bild(pfad, suchwort)

    geladen = finde_und_hole(
        suchwort, ziel, beobachter=mitschreiben, blick=hinsehen
    )

    if verworfen:
        console.print("\n[dim]Angesehen, aber nicht genommen:[/dim]")
        for seite, grund in verworfen:
            kurz = seite.rsplit("/", 1)[-1][:56]
            console.print(f"  [dim]{kurz}[/dim]  [yellow]{grund}[/yellow]")

    if geladen is None:
        console.print(
            Panel(
                "Aus den ersten Treffern ist nichts geworden - entweder gab\n"
                "es nichts frei Verwendbares in brauchbarer Größe, oder\n"
                "alles, was da war, hat die Prüfung oben verworfen.\n\n"
                "Im Zyklus würde der Agent hier ein Bild malen lassen.\n"
                "Probier ein allgemeineres Wort, oder Englisch statt Deutsch.",
                title="[yellow]Nichts Brauchbares gefunden[/yellow]",
            )
        )
        raise typer.Exit(1)

    gefunden = geladen
    breite, hoehe = gefunden.breite, gefunden.hoehe
    verhaeltnis = breite / hoehe if hoehe else 0
    pano = ist_panorama(ziel)
    stuecke = stueckzahl(breite, hoehe, 864 / 1080) if pano else 0

    # Wie das Bild im Beitrag ankommt - und das ist etwas anderes als
    # seine Groesse. Instagram nimmt nur bestimmte Seitenverhaeltnisse,
    # also wird mittig beschnitten, und was dabei uebrig bleibt, muss
    # 1080 Pixel breit werden. Reicht es nicht, wird hochgerechnet.
    from .imaging.echtbild import massfaktor, nutzmasse
    from .imaging.schaerfe import SCHARF_GENUG, schaerfewert

    nutz_b, nutz_h = nutzmasse(breite, hoehe)
    mass = massfaktor(breite, hoehe)
    schaerfe = schaerfewert(ziel)
    if mass >= 1.0:
        zuschnitt = (
            f"[green]{nutz_b} x {nutz_h}[/green] - wird verkleinert, bleibt scharf"
        )
    else:
        zuschnitt = (
            f"[yellow]{nutz_b} x {nutz_h}[/yellow] - muss um das "
            f"{1 / mass:.2f}-fache hochgerechnet werden"
        )
    if schaerfe <= 0:
        schaerfezeile = "nicht messbar"
    elif schaerfe >= SCHARF_GENUG:
        schaerfezeile = f"[green]scharf[/green] ({schaerfe:.2f})"
    else:
        schaerfezeile = f"[yellow]etwas weich[/yellow] ({schaerfe:.2f})"

    console.print(
        Panel(
            f"Quelle:   {gefunden.seite}\n"
            f"Lizenz:   [bold]{gefunden.lizenz}[/bold]\n"
            f"Urheber:  {gefunden.urheber or 'nicht genannt'}\n"
            f"Größe:    [bold]{breite} x {hoehe}[/bold] "
            f"(Verhältnis {verhaeltnis:.2f})\n"
            + (
                f"Panorama: [green]ja, {stuecke} Stücke zum Durchwandern[/green]\n"
                if stuecke >= 2
                else "Panorama: nein, gewöhnliches Format\n"
            )
            + f"Eignung:  [bold]{_eignung(verhaeltnis)}[/bold]\n"
            + f"Zuschnitt: {zuschnitt}\n"
            + f"Schärfe:  {schaerfezeile}\n"
            + (f"Angesehen: [bold]{gefunden.gesehen}[/bold]\n" if gefunden.gesehen else "")
            + f"\nLiegt hier: [bold]{ziel}[/bold]\n\n"
            f"[dim]Pflichtangabe im Beitrag:\n{gefunden.nachweis}[/dim]",
            title="[green]Gefunden[/green]",
        )
    )
    console.print(
        "\n[dim]Mach das Bild auf und schau, ob es zum Thema passt. "
        "Genau dieses würde im Beitrag landen.[/dim]"
    )


@app.command()
def quellprobe(
    adresse: str = typer.Argument(
        ..., help="Die Seite einer Studie oder Behörde, z. B. ein PLOS- oder NASA-Artikel"
    ),
    config: Path = typer.Option(None),
    ansehen: bool = typer.Option(
        False,
        "--ansehen",
        help="Jedes Bild kurz ansehen lassen - kostet rund 0,05 Cent je Bild",
    ),
) -> None:
    """Holt die Bilder vom Fund selbst aus der Originalquelle - ohne Zyklus.

    Das ist der Weg, auf dem der Agent zu Aufnahmen kommt, die den Fund
    wirklich zeigen: Studie oder Behoerde aufrufen, Lizenz auf der Seite
    pruefen, Bilder herunterladen, das beste nehmen. Hier laesst er sich
    an einer einzelnen Adresse ausprobieren, bevor ein Zyklus dafuer
    Geld ausgibt.
    """
    from .imaging.echtbild import massfaktor
    from .imaging.quellbild import aus_der_quelle, erkenne_quelle

    settings = load_settings(config)
    ziel_ordner = settings.media_dir
    ziel_ordner.mkdir(parents=True, exist_ok=True)

    quelle = erkenne_quelle(adresse)
    console.print(
        Panel(
            f"Seite: [bold]{adresse}[/bold]\n"
            + (
                f"Quelle: [green]{quelle.name}[/green] - "
                + (
                    "Behörde, gemeinfrei von Gesetzes wegen"
                    if quelle.gemeinfrei
                    else "Zeitschrift, der Lizenzvermerk muss auf der Seite stehen"
                )
                if quelle
                else "Quelle: [yellow]keine freie Quelle[/yellow] - "
                "die Seite wird gar nicht erst aufgerufen"
            ),
            title="Bild aus der Quelle",
        )
    )
    if quelle is None:
        console.print(
            "\nBilder von Nachrichtenseiten gehören fast immer einer Agentur.\n"
            "Gib die Adresse der Studie selbst ein - PLOS, Frontiers, Pensoft,\n"
            "Scientific Reports - oder die einer Behörde wie der NASA."
        )
        raise typer.Exit(1)

    hinsehen = None
    if ansehen:
        from .economy import Treasury
        from .llm import Brain
        from .store import Store

        gehirn = Brain(
            settings.llm, Treasury(Store(settings.db_path), settings.economy)
        )

        def hinsehen(pfad):  # noqa: F811 - bewusst erst hier definiert
            return gehirn.beurteile_bild(pfad, adresse)

    ziel = ziel_ordner / "quellprobe.jpg"
    verworfen: list[tuple[str, str]] = []
    weitere: list = []
    befunde: list = []

    def mitschreiben(bild, taugte: bool, grund: str) -> None:
        if not taugte:
            verworfen.append((bild.url, grund))

    console.print("\n[dim]Seite wird geladen ...[/dim]")
    gefunden = aus_der_quelle(
        [adresse],
        ziel,
        blick=hinsehen,
        beobachter=mitschreiben,
        weitere=weitere,
        befunde=befunde,
    )

    for befund in befunde:
        if befund.lizenz:
            console.print(f"Lizenz auf der Seite: [green]{befund.lizenz}[/green]")
        if befund.urheber:
            console.print(f"Zu nennen:            {befund.urheber}")
        if befund.kandidaten is not None:
            console.print(f"Bilder auf der Seite: {len(befund.kandidaten)}")

    fuers_karussell = {bild.url for bild in weitere}
    if verworfen:
        console.print("\n[dim]Angesehen:[/dim]")
        for url, grund in verworfen:
            kurz = url.rsplit("/", 1)[-1][:50]
            if url in fuers_karussell:
                console.print(f"  [dim]{kurz}[/dim]  [green]kommt ins Karussell[/green]")
            else:
                console.print(f"  [dim]{kurz}[/dim]  [yellow]{grund}[/yellow]")

    if gefunden is None:
        gruende = "; ".join(b.grund for b in befunde if b.grund) or "unbekannt"
        console.print(
            Panel(
                f"Von dieser Seite ist nichts brauchbar: {gruende}\n\n"
                "Im Zyklus würde der Agent jetzt im Bildarchiv suchen.",
                title="[yellow]Nichts genommen[/yellow]",
            )
        )
        raise typer.Exit(1)

    mass = massfaktor(gefunden.breite, gefunden.hoehe)
    console.print(
        Panel(
            f"Bild:     {gefunden.url}\n"
            f"Größe:    [bold]{gefunden.breite} x {gefunden.hoehe}[/bold]"
            + (
                " - wird verkleinert, bleibt scharf"
                if mass >= 1.0
                else f" - muss um das {1 / mass:.2f}-fache hochgerechnet werden"
            )
            + "\n"
            + (f"Angesehen: [bold]{gefunden.gesehen}[/bold]\n" if gefunden.gesehen else "")
            + f"\nLiegt hier: [bold]{ziel}[/bold]\n"
            + (
                "Dazu ein weiteres Bild von derselben Seite fürs Karussell\n"
                if len(weitere) == 1
                else f"Dazu {len(weitere)} weitere Bilder von derselben Seite fürs Karussell\n"
                if weitere
                else ""
            )
            + f"\n[dim]Pflichtangabe im Beitrag:\n{gefunden.nachweis}[/dim]",
            title="[green]Gefunden - ein Bild vom Fund selbst[/green]",
        )
    )


@app.command()
def karussellprobe(
    post_id: int = typer.Argument(0, help="Welcher Entwurf, 0 heisst der neueste"),
    config: Path = typer.Option(None),
) -> None:
    """Baut die Bilder eines vorhandenen Entwurfs noch einmal - ohne Modell.

    Der teuerste Weg, das Karussell auszuprobieren, waere ein ganzer
    Zyklus: Stoffsuche, Text, Pruefung, alles noch einmal bezahlt, nur um
    zu sehen, ob die Bilder zusammenpassen. Hier wird ein Entwurf
    genommen, der schon dasteht, und nur der Bildteil wiederholt.

    Was dabei wirklich laeuft: die Bildsuche in beiden Archiven, das
    Angleichen der ganzen Reihe, das Zerschneiden eines Panoramas und
    die Beschriftung. Was nicht laeuft: jeder Modellaufruf. Gemalt wird
    auch nicht - es geht um die echten Aufnahmen.
    """
    import json as _json

    from .imaging.angleichen import gleiche_reihe_an
    from .imaging.panorama import ist_panorama, zerschneide
    from .models import PostDraft

    agent = _agent(config)
    try:
        if post_id:
            zeile = agent.store.get_post(post_id)
            if zeile is None:
                console.print("[red]Diesen Entwurf gibt es nicht.[/red]")
                raise typer.Exit(1)
        else:
            # Den neuesten Entwurf zu nehmen, der Karten hat - nicht
            # einfach den neuesten. Sonst sieht man bei jedem Aufruf
            # "hat keine Karten", solange ein alter Entwurf obenauf
            # liegt, und haelt die Probe fuer kaputt.
            zeile = None
            letzter = None
            for kandidat in agent.store.recent_posts(limit=20):
                letzter = letzter or kandidat
                daten = _json.loads(kandidat["draft_json"])
                if daten.get("karten"):
                    zeile = kandidat
                    break
            if zeile is None:
                if letzter is None:
                    console.print(
                        "[yellow]Es gibt noch gar keinen Entwurf.[/yellow] "
                        "Lass erst einen Zyklus laufen."
                    )
                    raise typer.Exit(0)
                console.print(
                    Panel(
                        "Keiner der letzten 20 Entwuerfe hat Karten.\n\n"
                        "Das ist kein Fehler: Entwuerfe von vor dem Karussell\n"
                        "haben keine, und ein Fund, der nicht genug hergibt,\n"
                        "bekommt auch keine - ein starkes Bild schlaegt fuenf,\n"
                        "von denen drei nichts sagen.\n\n"
                        "[bold]Was jetzt hilft:[/bold] einen Zyklus laufen lassen.\n"
                        "Danach zeigt diese Probe, ob seine Bilder zusammenpassen -\n"
                        "und zwar so oft du willst, ohne dass es noch etwas kostet.",
                        title="[yellow]Noch nichts zum Ausprobieren[/yellow]",
                    )
                )
                raise typer.Exit(0)

        draft = PostDraft.model_validate(_json.loads(zeile["draft_json"]))
        identitaet = agent.identity
        if identitaet is None:
            console.print("[red]Es gibt noch kein Profil.[/red]")
            raise typer.Exit(1)

        karten = list(getattr(draft, "karten", None) or [])
        console.print(
            Panel(
                f"Entwurf:  [bold]{zeile['id']}[/bold] - {draft.bildtext[:60]}\n"
                f"Karten:   [bold]{len(karten)}[/bold] zusaetzlich zum ersten Bild\n"
                f"Farben:   {draft.visual.background_hex} / {draft.visual.accent_hex}\n\n"
                "[dim]Kein Modellaufruf, kein Malen - nur Suche, Angleichen\n"
                "und Beschriften. Kostet nichts.[/dim]",
                title="Karussellprobe",
            )
        )
        if not karten:
            # Nur noch erreichbar, wenn jemand ausdruecklich eine Nummer
            # genannt hat - sonst sucht die Auswahl oben schon einen mit.
            console.print(
                "[yellow]Dieser Entwurf hat keine Karten.[/yellow] "
                "Er stammt von vor dem Karussell, oder der Agent fand den "
                "Fund nicht ergiebig genug. Ohne Nummer sucht die Probe "
                "sich den neuesten mit Karten."
            )
            raise typer.Exit(0)

        stamm = f"probe-{zeile['id']}"
        rohbilder = []
        for nummer, karte in enumerate(karten, start=2):
            roh, nachweis = agent._karte_rohbild(karte, stamm, nummer)
            rohbilder.append(roh)
            woher = "echte Aufnahme" if nachweis else ("gemalt" if roh else "nichts")
            console.print(f"  Karte {nummer}: {karte.text[:46]:<46} {woher}")

        echte = [b for b in rohbilder if b is not None]
        if len(echte) > 1:
            angeglichen = gleiche_reihe_an(
                echte,
                hintergrund_hex=draft.visual.background_hex,
                akzent_hex=draft.visual.accent_hex,
            )
            console.print(f"\n  Angeglichen: {angeglichen} von {len(echte)} Bildern")

        fertige = []
        for versatz, (karte, roh) in enumerate(zip(karten, rohbilder)):
            fertige.append(
                agent._beschrifte_karte(karte, roh, stamm, versatz + 2, draft, identitaet)
            )

        pano = [b for b in rohbilder if b is not None and ist_panorama(b)]
        if pano:
            stuecke = zerschneide(
                pano[0], agent.settings.media_dir / f"{stamm}-pano",
                format_breite=864, format_hoehe=1080,
            )
            if stuecke:
                console.print(
                    f"  Panorama gefunden: {len(stuecke)} Stuecke zum Durchwandern"
                )

        console.print(
            Panel(
                "\n".join(f"  {p}" for p in fertige),
                title=f"[green]{len(fertige)} Bilder gebaut[/green]",
            )
        )
        console.print(
            "[dim]Mach sie nebeneinander auf. Die Frage ist nicht, ob jedes "
            "fuer sich gut ist, sondern ob sie zusammen aussehen.[/dim]"
        )
    finally:
        agent.close()


@app.command()
def bildtest(config: Path = typer.Option(None)) -> None:
    """Erzeugt ein einzelnes Probebild und sagt genau, was dabei passiert.

    Gedacht fuer den Fall, dass im Zyklus kein Bild herauskam und man
    nicht weiss, woran es lag.
    """
    from .imaging.generator import baue_generator

    settings = load_settings(config)

    console.print(f"Anbieter: [bold]{settings.bild.anbieter}[/bold]")
    console.print(f"Modell:   [bold]{settings.bild.modell or '(voreingestellt)'}[/bold]")
    if settings.bild.token:
        sichtbar = settings.bild.token
        if settings.bild.anbieter != "lokal":
            sichtbar = f"{sichtbar[:6]}…{sichtbar[-4:]} ({len(sichtbar)} Zeichen)"
        console.print(f"Zugang:   [bold]{sichtbar}[/bold]")
    else:
        console.print("Zugang:   [red]keiner hinterlegt[/red]")

    generator = baue_generator(
        settings.bild.anbieter,
        settings.bild.token,
        settings.bild.modell,
        art=settings.bild.art,
    )
    if generator is None:
        console.print(
            "\n[red]Es wurde gar kein Bilddienst aufgebaut.[/red]\n"
            "Richte ihn ein mit: [bold]insta-agent bilder[/bold]"
        )
        raise typer.Exit(1)

    ziel = settings.media_dir / "probebild.png"
    console.print("\n[dim]Erzeuge ein Probebild, das dauert einen Moment ...[/dim]")

    try:
        generator.erzeuge(
            "A single weathered wooden chair in an empty room, one shaft of cold "
            "morning light from a tall window, deep shadows, 35mm film grain, "
            "muted blue and amber, no text, no logos, vertical 9:16",
            ziel,
        )
    except Exception as exc:  # noqa: BLE001 - hier ist der Fehler das Ergebnis
        console.print(f"\n[red]Kein Bild.[/red]\n{exc}")
        raise typer.Exit(1) from None
    finally:
        if hasattr(generator, "close"):
            generator.close()

    groesse = ziel.stat().st_size
    console.print(
        f"\n[green]Bild erzeugt.[/green] {groesse // 1024} KB\n"
        f"Es liegt hier: [bold]{ziel}[/bold]\n"
        "[dim]Mach es auf und schau es dir an - dann weisst du, dass die "
        "Kette steht.[/dim]"
    )


@app.command()
def neustart(
    config: Path = typer.Option(None),
    ja: bool = typer.Option(False, "--ja", help="Ohne Rückfrage durchführen"),
) -> None:
    """Lässt den Agenten seine Nische, seinen Namen und seine Strategie neu suchen.

    Veröffentlichte Beiträge, Kasse und Journal bleiben erhalten. Der
    nächste Zyklus beginnt wieder bei der Marktanalyse - und kostet
    entsprechend.
    """
    agent = _agent(config)
    try:
        alt = agent.identity
        if alt:
            console.print(
                Panel(
                    f"[bold]{alt.agent_name}[/bold] · @{alt.handle}\n"
                    f"[dim]{alt.niche}[/dim]",
                    title="Das wirft er weg",
                )
            )
        else:
            console.print("[dim]Er hat noch kein Profil - es gibt nichts wegzuwerfen.[/dim]")

        if not ja and not _bestaetigt("Wirklich neu anfangen?"):
            console.print("Abgebrochen. Es bleibt alles, wie es war.")
            raise typer.Exit(0)

        geloescht = agent.neu_erfinden()
        console.print(
            f"[green]Fertig.[/green] {len(geloescht)} Entscheidungen gelöscht.\n"
            "Beim nächsten Lauf recherchiert er neu und erfindet sich neu.\n"
            "[dim]Denk daran, danach auch Instagram-Name und Bio anzupassen.[/dim]"
        )
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
                f"[dim]Der Agent nennt sich[/dim] [bold]{ident.agent_name}[/bold]\n"
                f"[dim]{ident.agent_why}[/dim]\n\n"
                f"Handle:      @{ident.handle}\n"
                f"Name:        {ident.display_name}\n"
                f"Nische:      {ident.niche}\n"
                f"Zielgruppe:  {ident.target_audience}\n"
                f"Tonfall:     {ident.tone_of_voice}\n"
                f"Bildsprache: {ident.visual_identity}\n"
                f"Säulen:      {', '.join(ident.content_pillars)}\n\n"
                f"[dim]Bio:[/dim] {ident.bio}\n\n"
                f"[dim]Begründung:[/dim] {ident.why_this_works}",
                title="Wer er ist und was er aufbaut",
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
