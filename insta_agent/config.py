"""Konfiguration: Umgebungsvariablen + YAML-Datei, beides optional."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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
        values[key.strip()] = value.strip().strip('"').strip("'")

    for key, value in values.items():
        os.environ.setdefault(key, value)


@dataclass(slots=True)
class LLMConfig:
    model: str = "claude-opus-5"
    # Günstigeres Modell für Routinearbeit (Hashtags, Umformulierungen).
    cheap_model: str = "claude-haiku-4-5"
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
    # Ohne --live veröffentlicht der Agent nichts, er schreibt nur Entwürfe.
    live: bool = False


@dataclass(slots=True)
class Settings:
    llm: LLMConfig = field(default_factory=LLMConfig)
    economy: EconomyConfig = field(default_factory=EconomyConfig)
    posting: PostingConfig = field(default_factory=PostingConfig)

    db_path: Path = REPO_ROOT / "state" / "agent.db"
    media_dir: Path = REPO_ROOT / "out" / "media"
    draft_dir: Path = REPO_ROOT / "out" / "drafts"

    anthropic_api_key: str | None = None
    ig_user_id: str | None = None
    ig_access_token: str | None = None
    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    public_media_base_url: str | None = None

    @property
    def instagram_ready(self) -> bool:
        return bool(self.ig_user_id and self.ig_access_token)

    @property
    def can_publish(self) -> bool:
        """Veröffentlichen geht nur mit API-Zugang UND öffentlicher Bild-URL."""
        return self.instagram_ready and bool(self.public_media_base_url)


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

    settings.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    settings.ig_user_id = os.getenv("IG_USER_ID") or None
    settings.ig_access_token = os.getenv("IG_ACCESS_TOKEN") or None
    settings.meta_app_id = os.getenv("META_APP_ID") or None
    settings.meta_app_secret = os.getenv("META_APP_SECRET") or None
    settings.public_media_base_url = (os.getenv("PUBLIC_MEDIA_BASE_URL") or "").rstrip("/") or None

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
