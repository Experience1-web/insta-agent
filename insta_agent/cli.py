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

    console.print(
        Panel(
            "Der Agent schreibt die Bildbeschreibung selbst. Malen lassen muss\n"
            "er sie woanders - Claude kann das nicht.\n\n"
            "[bold]1  Google Gemini[/bold]  [green]kostenlos moeglich[/green]\n"
            "   Schluessel auf aistudio.google.com, ohne Zahlungsdaten.\n"
            "   Google gibt ein Freikontingent pro Tag - knapp, aber fuer\n"
            "   ein paar Beitraege reicht es. Ist es aufgebraucht, bleibt es\n"
            "   bis zum naechsten Tag bei der Typografie.\n\n"
            "[bold]2  Eigener Rechner[/bold]  [green]dauerhaft kostenlos[/green]\n"
            "   Braucht eine NVIDIA-Karte ab 8 GB und ein laufendes\n"
            "   Bildprogramm (AUTOMATIC1111, Forge, SD.Next) mit --api.\n"
            "   Einmal aufbauen, danach keine Grenzen.\n\n"
            "[bold]3  Replicate[/bold]  wenige Cent je Bild\n"
            "   Kein Aufbau, keine Grenzen, beste Qualitaet.",
            title="Wer malt die Bilder?",
        )
    )

    wahl = typer.prompt("Welcher Weg? [1/2/3]", default="1").strip()[:1]

    if wahl == "2":
        adresse = typer.prompt("Adresse des Bildprogramms", default="http://127.0.0.1:7860")
        set_env_value("BILD_ANBIETER", "lokal")
        set_env_value("BILD_TOKEN", adresse.strip().rstrip("/"))
        set_env_value("BILD_KOSTEN", "0")
        modell = typer.prompt(
            "Name der Modelldatei (leer lassen fuer die geladene)", default=""
        ).strip()
        set_env_value("BILD_MODELL", modell)
        console.print(
            "\n[green]Eingetragen.[/green] Lass das Bildprogramm laufen, wenn der "
            "Agent arbeitet."
        )
        _bild_fertig()
        return

    if wahl == "3":
        token = _frag_schluessel("Schluessel von replicate.com")
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

    token = _frag_schluessel("Schluessel von aistudio.google.com")
    set_env_value("BILD_ANBIETER", "gemini")
    set_env_value("BILD_TOKEN", token)
    set_env_value("BILD_MODELL", "gemini-2.5-flash-image")
    set_env_value("BILD_KOSTEN", "0")
    console.print(
        "\n[dim]Falls du dort spaeter Zahlungsdaten hinterlegst, trag die Kosten\n"
        "pro Bild mit `insta-agent bilder` neu ein - sonst rechnet er mit null.[/dim]"
    )
    _bild_fertig()


def _frag_schluessel(frage: str) -> str:
    """Fragt einen Schluessel ab und raeumt Einfuege-Unfaelle weg."""
    roh = typer.prompt(frage, hide_input=True)
    # Mehrzeiliges Einfuegen zerlegt den Schluessel sonst still.
    token = "".join(roh.split()).strip("\"'")
    if not token:
        console.print("[yellow]Nichts eingetragen.[/yellow]")
        raise typer.Exit(1)
    return token


def _bild_fertig() -> None:
    console.print(
        "\n[green]Eingetragen.[/green] Ab dem naechsten Zyklus malt er seine "
        "Bilder selbst.\n[dim]Pruefen: insta-agent check[/dim]"
    )


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
            "  App auswaehlen, diese Berechtigungen anhaken:\n"
            "    instagram_basic\n"
            "    instagram_content_publish\n"
            "    pages_show_list\n"
            "    pages_read_engagement\n"
            "  dann auf 'Generate Access Token' und den Text kopieren.\n\n"
            "[yellow]Dieser Schluessel haelt nur ein bis zwei Stunden.[/yellow]\n"
            "Mach den Rest gleich danach - ich tausche ihn hier gegen einen\n"
            "dauerhaften.",
            title="Instagram-Zugang einrichten",
        )
    )

    app_id = typer.prompt("App-ID").strip()
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
    console.print(
        "\n[dim]Es fehlt noch ein oeffentlicher Platz fuer die Bilder -\n"
        "Instagram holt sie sich von einer Adresse im Netz.[/dim]"
    )


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
        settings.bild.anbieter, settings.bild.token, settings.bild.modell
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
