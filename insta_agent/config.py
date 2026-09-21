"""Konfiguration: Umgebungsvariablen + YAML-Datei, beides optional."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "agent.yaml"
EXAMPLE_CONFIG = REPO_ROOT / "config" / "agent.example.yaml"
ENV_PATH = REPO_ROOT / ".env"
EXAMPLE_ENV = REPO_ROOT / ".env.example"


def set_env_value(key: str, value: str, path: Path | None = None) -> Path:
    """Trägt einen Wert in die .env ein - ersetzend, nicht anhängend.

    Legt die Datei aus der Beispieldatei an, falls es sie noch nicht gibt.
    Eine schon vorhandene Zeile mit diesem Schlüssel wird ersetzt, auch
    wenn sie auskommentiert ist. So entstehen keine Doppeleinträge, über
    die man später stolpert.
    """
    if "\n" in value or "\r" in value:
        raise ValueError(
            "Der Wert enthält einen Zeilenumbruch. Ein Eintrag in der .env muss "
            "auf eine einzige Zeile passen - sonst landet der Rest als kaputte "
            "Zeile in der Datei und wird beim Lesen stillschweigend verschluckt."
        )

    target = path or ENV_PATH
    if not target.exists():
        target.write_text(
            EXAMPLE_ENV.read_text(encoding="utf-8") if EXAMPLE_ENV.exists() else "",
            encoding="utf-8",
        )

    lines = target.read_text(encoding="utf-8").splitlines()
    new_line = f"{key}={value}"
    ersetzt = False

    for index, raw in enumerate(lines):
        blank = raw.strip().lstrip("#").strip()
        if blank.startswith(f"{key}="):
            lines[index] = new_line
            ersetzt = True
            break

    if not ersetzt:
        lines.append(new_line)

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _unquote(value: str) -> str:
    """Entfernt Anführungszeichen nur, wenn der Wert wirklich eingefasst ist.

    Ein blindes strip('"') würde auch ein einzelnes Zeichen am Ende
    abschneiden - und ein um ein Zeichen verkürzter Schlüssel ist schlimmer
    als einer mit sichtbarem Anführungszeichen: Der erste scheitert später
    mit einer nichtssagenden Fehlermeldung, der zweite fällt sofort auf.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _load_dotenv(path: Path) -> None:
    """Minimaler .env-Loader, damit keine weitere Abhängigkeit nötig ist.

    Zwei Vorrangregeln, in dieser Reihenfolge:
      1. Steht ein Schlüssel mehrfach in der Datei, gilt der letzte. So
         überschreibt eine angehängte Zeile die Platzhalterzeile darüber,
         statt wirkungslos zu bleiben.
      2. Eine echte Umgebungsvariable schlägt die Datei immer.
    """
    if not path.exists():
        return

    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = _unquote(value.strip())

    for key, value in values.items():
        os.environ.setdefault(key, value)


@dataclass(slots=True)
class LLMConfig:
    model: str = "claude-opus-5"
    # Günstigeres Modell für Routinearbeit (Hashtags, Umformulierungen).
    cheap_model: str = "claude-haiku-4-5"
    # Die Websuche ist der teuerste Einzelschritt. Sie braucht kein
    # Spitzenmodell - Seiten lesen und zusammenfassen kann auch Sonnet,
    # zu einem Bruchteil der Kosten.
    research_model: str = "claude-sonnet-5"
    research_effort: str = "medium"
    max_web_searches: int = 4

    # Wohin der Agent ausweicht, wenn ein Aufruf mit stop_reason "refusal" endet.
    fallback_model: str = "claude-opus-4-8"
    effort: str = "high"
    max_tokens: int = 16000


@dataclass(slots=True)
class EconomyConfig:
    treasury_start_usd: float = 20.0
    # Unter diesem Rest-Guthaben fährt der Agent nur noch Sparbetrieb.
    low_balance_usd: float = 5.0
    # Darunter stoppt er komplett und meldet sich beim Betreiber.
    halt_balance_usd: float = 0.50
    # Harte Obergrenze pro Zyklus, verhindert Ausreißer.
    max_cost_per_cycle_usd: float = 1.50


@dataclass(slots=True)
class PostingConfig:
    posts_per_day: int = 1
    # Lokale Uhrzeiten, zu denen der Agent veröffentlichen darf.
    preferred_hours: list[int] = field(default_factory=lambda: [8, 12, 18])
    max_hashtags: int = 20
    # "feed" ist 4:5, "story" ist 9:16. Voreinstellung ist feed: Instagram
    # nimmt im Feed nur Bilder zwischen 4:5 und 1.91:1 an - 9:16 liegt
    # ausserhalb und wuerde beschnitten.
    bildformat: str = "feed"
    # Der Account steht fest und wird nicht mehr erfunden: Wer sich eine
    # Nische selbst sucht, waehlt eine enge, weil enge Nischen sich besser
    # begruenden lassen - und genau das war nicht gewollt. Auf True darf
    # der Agent wieder selbst suchen; dann kostet der erste Lauf eine
    # Marktrecherche mehr.
    identitaet_frei: bool = False
    # Vor jedem Beitrag sucht die Stoffsuche den Fund, ueber den
    # geschrieben wird. Abschalten spart einen Aufruf - und der Agent
    # schreibt dann wieder ueber das, was ihm gerade einfaellt. Das ist
    # erfahrungsgemaess Alltag.
    stoff_noetig: bool = True
    # Die Bildsprache sieht sich den Prompt an, bevor gemalt wird, und
    # liefert die bessere Fassung. Abschalten spart einen Aufruf und
    # kostet den Unterschied zwischen eigenem Bild und Massenware.
    gestaltung_noetig: bool = True
    # Wie oft ein beanstandeter Beitrag selbsttaetig nachgebessert wird,
    # bevor er dem Betreiber vorgelegt wird. Jede Runde kostet: einmal neu
    # schreiben, einmal neu pruefen. Eine Runde faengt das meiste ab; wer
    # danach noch Befunde hat, hat meist ein Thema erwischt, das nicht
    # traegt - dann entscheidet besser ein Mensch als eine dritte Runde.
    nachbesserungen: int = 1
    # Jeder Entwurf geht durch die Endpruefung, bevor er vorgelegt wird.
    # Abschalten spart Geld und kostet die einzige Kontrolle, die es gibt.
    pruefung_noetig: bool = True
    # Solange True, geht nur nach draussen, was der Betreiber freigegeben hat.
    # Auf False wird jeder geschriebene Beitrag sofort veroeffentlicht -
    # das gehoert erst eingeschaltet, wenn die Beitraege verlaesslich taugen.
    freigabe_noetig: bool = True
    # Ohne --live veröffentlicht der Agent nichts, er schreibt nur Entwürfe.
    live: bool = False


@dataclass(slots=True)
class BildConfig:
    """Der Dienst, der die Bilder malt.

    Claude erzeugt keine Bilder. Für einen bildgetriebenen Account braucht
    es deshalb einen zweiten Anbieter mit eigenem Schlüssel und eigenem
    Guthaben. Ohne Schlüssel bleibt es bei der typografischen Fassung -
    das ist kein Fehler, nur weniger.
    """

    # "replicate" laesst beim Anbieter malen, "lokal" auf dem eigenen
    # Rechner. Lokal kostet nichts ausser Strom und Rechenzeit.
    anbieter: str = "replicate"
    modell: str = "black-forest-labs/flux-1.1-pro"
    # Beim Anbieter der Schluessel, beim lokalen Weg die Adresse des
    # eigenen Bildprogramms.
    token: str | None = None
    # Was ein Bild beim Anbieter kostet. Steht auf dessen Preisseite und
    # ändert sich dort, nicht hier - deshalb einstellbar statt fest
    # verdrahtet. Der Agent bucht diesen Betrag in seine Kasse, sonst
    # wüsste er nicht, was ein Beitrag ihn wirklich kostet.
    kosten_pro_bild_usd: float = 0.04
    # Nur fuer den eigenen Rechner: "flux", "sdxl" oder "sd15". Leer heisst
    # "am Namen erkennen". Die Erkennung liegt fast immer richtig, aber
    # wenn nicht, malt das Modell auf falschen Massen - und das sieht man
    # dem Bild sofort an. Deshalb ueberschreibbar.
    art: str = ""

    @property
    def aktiv(self) -> bool:
        """Der lokale Weg braucht keinen Schluessel, nur ein laufendes Programm."""
        return self.anbieter == "lokal" or bool(self.token)


@dataclass(slots=True)
class Settings:
    llm: LLMConfig = field(default_factory=LLMConfig)
    economy: EconomyConfig = field(default_factory=EconomyConfig)
    posting: PostingConfig = field(default_factory=PostingConfig)
    bild: BildConfig = field(default_factory=BildConfig)

    db_path: Path = REPO_ROOT / "state" / "agent.db"
    media_dir: Path = REPO_ROOT / "out" / "media"
    draft_dir: Path = REPO_ROOT / "out" / "drafts"

    anthropic_api_key: str | None = None
    # Nur zum Lesen der Abrechnung, damit die Kasse ohne Zutun stimmt.
    # Ein Admin-Schlüssel kann mehr als das, deshalb wird er ausschließlich
    # in economy/abrechnung.py verwendet und gerät nie in einen Prompt.
    admin_api_key: str | None = None
    ig_user_id: str | None = None
    ig_access_token: str | None = None
    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    public_media_base_url: str | None = None
    # Wohin die fertigen Bilder kurz hochgeladen werden, damit Instagram
    # sie abholen kann. Ohne das - und ohne public_media_base_url - kann
    # der Agent nicht veroeffentlichen.
    ablage_anbieter: str = "litterbox"
    ablage_token: str | None = None
    wallet_address: str | None = None
    """Empfangsadresse. Nur zum Empfangen - der Agent hat keine Schlüssel."""

    wallet_chain: str | None = None
    web_token: str | None = None
    """Zugangswort für die Oberfläche, sobald sie über 127.0.0.1 hinaus lauscht."""

    @property
    def abrechnung_schluessel(self) -> str | None:
        """Der Schlüssel, mit dem die Abrechnung gelesen wird.

        Zuerst der eigens dafür eingetragene. Ohne den wird der normale
        API-Schlüssel versucht: Ist er persönlich und nicht auf einen
        Arbeitsbereich beschränkt, darf er die Abrechnung lesen - dann
        braucht es gar keinen zweiten Schlüssel. Darf er es nicht, kommt
        eine Absage und es bleibt beim Eintragen von Hand. Etwas kaputt
        gehen kann dabei nicht: Es ist ein lesender Aufruf.
        """
        return self.admin_api_key or self.anthropic_api_key

    @property
    def instagram_ready(self) -> bool:
        return bool(self.ig_user_id and self.ig_access_token)

    @property
    def hat_bildplatz(self) -> bool:
        """Ob es eine Adresse gibt, von der Instagram das Bild holen kann."""
        from .instagram.ablage import OHNE_SCHLUESSEL

        if self.public_media_base_url or self.ablage_token:
            return True
        # Manche Bildspeicher brauchen weder Konto noch Schlüssel - dann
        # ist nichts einzurichten und es kann sofort losgehen.
        return self.ablage_anbieter in OHNE_SCHLUESSEL

    @property
    def can_publish(self) -> bool:
        """Ob alles eingerichtet ist, was zum Veröffentlichen nötig wäre."""
        return self.instagram_ready and self.hat_bildplatz

    @property
    def postet_wirklich(self) -> bool:
        """Ob ein freigegebener Beitrag auch tatsächlich hinausgeht.

        `posting.live` ist die Hauptsicherung: Solange sie aus ist, macht
        der Verlag einen Trockenlauf und legt nur Entwürfe ab. Sie muss
        einmal bewusst eingeschaltet werden, damit niemand versehentlich
        unter seinem Namen veröffentlicht.
        """
        return self.can_publish and self.posting.live


def _merge(section: Any, data: dict[str, Any] | None) -> None:
    for key, value in (data or {}).items():
        if hasattr(section, key):
            setattr(section, key, value)


def load_settings(config_path: Path | None = None) -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    settings = Settings()

    path = config_path or DEFAULT_CONFIG
    if not path.exists() and EXAMPLE_CONFIG.exists():
        path = EXAMPLE_CONFIG
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        _merge(settings.llm, raw.get("llm"))
        _merge(settings.economy, raw.get("economy"))
        _merge(settings.posting, raw.get("posting"))
        _merge(settings.bild, raw.get("bild"))

    settings.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    settings.admin_api_key = os.getenv("ANTHROPIC_ADMIN_KEY") or None
    if anbieter := os.getenv("BILD_ANBIETER"):
        settings.bild.anbieter = anbieter
    settings.bild.token = (
        os.getenv("BILD_TOKEN") or os.getenv("REPLICATE_API_TOKEN") or None
    )
    if modell := os.getenv("BILD_MODELL"):
        settings.bild.modell = modell
    if art := os.getenv("BILD_ART"):
        settings.bild.art = art.strip().casefold()
    if preis := os.getenv("BILD_KOSTEN"):
        try:
            settings.bild.kosten_pro_bild_usd = float(preis)
        except ValueError:
            log.warning("BILD_KOSTEN ist keine Zahl (%r) - Voreinstellung bleibt", preis)
    settings.ig_user_id = os.getenv("IG_USER_ID") or None
    settings.ig_access_token = os.getenv("IG_ACCESS_TOKEN") or None
    settings.meta_app_id = os.getenv("META_APP_ID") or None
    settings.meta_app_secret = os.getenv("META_APP_SECRET") or None
    settings.public_media_base_url = (os.getenv("PUBLIC_MEDIA_BASE_URL") or "").rstrip("/") or None
    if (scharf := os.getenv("POSTING_LIVE")) is not None:
        settings.posting.live = scharf.strip().lower() in ("1", "true", "ja", "wahr", "an")
    settings.ablage_token = os.getenv("ABLAGE_TOKEN") or None
    if anbieter := os.getenv("ABLAGE_ANBIETER"):
        settings.ablage_anbieter = anbieter
    settings.web_token = os.getenv("WEB_TOKEN") or None
    settings.wallet_address = os.getenv("WALLET_ADDRESS") or None
    settings.wallet_chain = os.getenv("WALLET_CHAIN") or None

    if media := os.getenv("PUBLIC_MEDIA_DIR"):
        settings.media_dir = Path(media)
    if start := os.getenv("TREASURY_START_USD"):
        settings.economy.treasury_start_usd = float(start)

    for directory in (settings.db_path.parent, settings.media_dir, settings.draft_dir):
        directory.mkdir(parents=True, exist_ok=True)

    _warn_about_unusable_budget(settings.economy)
    return settings


def _warn_about_unusable_budget(economy: EconomyConfig) -> None:
    """Warnt vor Schwellen, die sich gegenseitig aufheben.

    Liegt die Sparschwelle über dem Startkapital, arbeitet der Agent vom
    ersten Zyklus an im Sparbetrieb - ohne dass jemand versteht, warum er
    nur noch das billige Modell nutzt.
    """
    log = logging.getLogger(__name__)
    if economy.treasury_start_usd <= economy.halt_balance_usd:
        log.warning(
            "Startkapital (%.2f USD) liegt auf oder unter der Stoppgrenze (%.2f USD) - "
            "der Agent hält sofort an.",
            economy.treasury_start_usd,
            economy.halt_balance_usd,
        )
    elif economy.treasury_start_usd <= economy.low_balance_usd:
        log.warning(
            "Startkapital (%.2f USD) liegt auf oder unter der Sparschwelle (%.2f USD) - "
            "der Agent läuft von Anfang an im Sparbetrieb.",
            economy.treasury_start_usd,
            economy.low_balance_usd,
        )
