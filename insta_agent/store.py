"""Das Langzeitgedächtnis des Agenten: eine einzelne SQLite-Datei.

Alles, was der Agent über sich, seinen Markt, seine Posts und sein Geld
weiß, liegt hier. Ein Zyklus lädt den Zustand, denkt, schreibt zurück.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence
from typing import Any, Iterator

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    published_at    TEXT,
    ig_media_id     TEXT,
    pillar          TEXT,
    caption         TEXT NOT NULL,
    hashtags        TEXT NOT NULL,
    image_path      TEXT,
    draft_json      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',
    pruefung_json   TEXT,
    gestaltung_json TEXT
);

CREATE TABLE IF NOT EXISTS insights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at   TEXT NOT NULL,
    ig_media_id   TEXT,
    metric        TEXT NOT NULL,
    value         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at  TEXT NOT NULL,
    kind         TEXT NOT NULL,           -- 'cost' oder 'revenue'
    category     TEXT NOT NULL,
    amount_usd   REAL NOT NULL,           -- Kosten negativ, Einnahmen positiv
    note         TEXT,
    meta         TEXT
);

CREATE TABLE IF NOT EXISTS journal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at  TEXT NOT NULL,
    cycle        INTEGER,
    kind         TEXT NOT NULL,
    message      TEXT NOT NULL,
    payload      TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_insights_media ON insights(ig_media_id);
CREATE INDEX IF NOT EXISTS idx_ledger_kind ON ledger(kind);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._ergaenze_spalten()
        self._conn.commit()

    # Spalten, die später dazugekommen sind. `CREATE TABLE IF NOT EXISTS`
    # fasst eine bestehende Tabelle nicht an, also müssen sie einzeln
    # nachgezogen werden - sonst scheitert jede Datenbank, die es schon
    # vor der Änderung gab.
    NACHGETRAGEN = {"posts": {"pruefung_json": "TEXT", "gestaltung_json": "TEXT"}}

    def _ergaenze_spalten(self) -> None:
        for tabelle, spalten in self.NACHGETRAGEN.items():
            vorhanden = {
                r["name"] for r in self._conn.execute(f"PRAGMA table_info({tabelle})")
            }
            for name, typ in spalten.items():
                if name not in vorhanden:
                    self._conn.execute(f"ALTER TABLE {tabelle} ADD COLUMN {name} {typ}")
                    log.info("Spalte %s.%s nachgetragen", tabelle, name)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- Schlüssel/Wert: Identität, Strategie, letzte Analyse ------------

    def set_json(self, key: str, value: Any) -> None:
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(payload, ensure_ascii=False), _now()),
            )

    def get_json(self, key: str) -> Any | None:
        row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def get_model(self, key: str, model_cls: type) -> Any | None:
        raw = self.get_json(key)
        return model_cls.model_validate(raw) if raw is not None else None

    # -- Posts -------------------------------------------------------------

    def add_draft(self, draft: Any, image_path: str | None) -> int:
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO posts(created_at, pillar, caption, hashtags, image_path, draft_json, status) "
                "VALUES(?,?,?,?,?,?,'draft')",
                (
                    _now(),
                    draft.pillar,
                    draft.caption,
                    json.dumps(draft.hashtags, ensure_ascii=False),
                    image_path,
                    json.dumps(draft.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

    def set_pruefung(self, post_id: int, bericht: Any) -> None:
        """Hängt den Bericht der Endprüfung an den Entwurf."""
        self._haenge_an(post_id, "pruefung_json", bericht)

    def set_gestaltung(self, post_id: int, urteil: Any) -> None:
        """Hängt das Urteil der Bildsprache an den Entwurf."""
        self._haenge_an(post_id, "gestaltung_json", urteil)

    def _haenge_an(self, post_id: int, spalte: str, inhalt: Any) -> None:
        payload = inhalt.model_dump(mode="json") if hasattr(inhalt, "model_dump") else inhalt
        with self._tx() as conn:
            conn.execute(
                f"UPDATE posts SET {spalte}=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), post_id),
            )

    def mark_published(self, post_id: int, ig_media_id: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE posts SET status='published', published_at=?, ig_media_id=? WHERE id=?",
                (_now(), ig_media_id, post_id),
            )

    def pending_drafts(self, limit: int = 10) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM posts WHERE status='draft' ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()

    # -- Freigabe ----------------------------------------------------------
    #
    # Der Agent schreibt, der Betreiber entscheidet. Nichts geht ohne ein
    # ausdrückliches Ja nach draußen - deshalb ist 'draft' der Anfang und
    # nicht schon die Erlaubnis.

    def freigeben(self, post_id: int) -> bool:
        """Gibt einen Entwurf zum Veröffentlichen frei.

        Gibt zurück, ob sich wirklich etwas geändert hat. Ein bereits
        veröffentlichter Beitrag lässt sich nicht nachträglich freigeben -
        sonst würde er beim nächsten Zyklus ein zweites Mal hochgeladen.
        """
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE posts SET status='approved' WHERE id=? AND status='draft'",
                (post_id,),
            )
            return cur.rowcount > 0

    def verwerfen(self, post_id: int) -> bool:
        """Legt einen Entwurf zur Seite. Er bleibt lesbar, geht aber nie raus."""
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE posts SET status='discarded' WHERE id=? AND status IN ('draft','approved')",
                (post_id,),
            )
            return cur.rowcount > 0

    def verwirf_alle_offenen(self) -> int:
        """Legt alles zur Seite, was noch nicht veröffentlicht wurde.

        Gedacht für den Neuanfang: Entwürfe aus einer aufgegebenen Nische
        passen nicht mehr zum neuen Profil, und ein versehentliches
        Freigeben würde sie trotzdem hinausschicken. Veröffentlichtes
        bleibt unberührt - das steht bereits auf Instagram.
        """
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE posts SET status='discarded' WHERE status IN ('draft','approved')"
            )
            return cur.rowcount

    def approved_drafts(self, limit: int = 10) -> list[sqlite3.Row]:
        """Was der Betreiber freigegeben hat - in der Reihenfolge des Schreibens."""
        return self._conn.execute(
            "SELECT * FROM posts WHERE status='approved' ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()

    def mark_failed(self, post_id: int, grund: str) -> None:
        """Veröffentlichen ging schief - der Beitrag bleibt freigegeben.

        Er wird beim nächsten Zyklus erneut versucht; der Grund landet im
        Journal, damit man sieht, woran es hängt.
        """
        self.log("publish_error", f"Beitrag {post_id}: {grund}")

    def recent_posts(self, limit: int = 15) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def published_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE status='published'"
        ).fetchone()
        return int(row["n"])

    # -- Kennzahlen --------------------------------------------------------

    def record_insight(self, metric: str, value: float, ig_media_id: str | None = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO insights(captured_at, ig_media_id, metric, value) VALUES(?,?,?,?)",
                (_now(), ig_media_id, metric, float(value)),
            )

    def latest_metric(self, metric: str) -> float | None:
        row = self._conn.execute(
            "SELECT value FROM insights WHERE metric=? ORDER BY id DESC LIMIT 1", (metric,)
        ).fetchone()
        return float(row["value"]) if row else None

    def metric_history(self, metric: str, limit: int = 30) -> list[tuple[str, float]]:
        rows = self._conn.execute(
            "SELECT captured_at, value FROM insights WHERE metric=? ORDER BY id DESC LIMIT ?",
            (metric, limit),
        ).fetchall()
        return [(r["captured_at"], float(r["value"])) for r in reversed(rows)]

    # -- Journal -----------------------------------------------------------

    def log(self, kind: str, message: str, cycle: int | None = None, payload: Any = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO journal(occurred_at, cycle, kind, message, payload) VALUES(?,?,?,?,?)",
                (
                    _now(),
                    cycle,
                    kind,
                    message,
                    json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
                ),
            )

    def recent_journal(self, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def last_cycle_at(self) -> datetime | None:
        """Ende des letzten abgeschlossenen Zyklus.

        Grundlage für den Arbeitstakt: Ohne diese Angabe würde der Agent
        bei jedem Neustart des Rechners erneut losarbeiten und Geld
        ausgeben.
        """
        row = self._conn.execute(
            "SELECT occurred_at FROM journal WHERE kind='cycle' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return datetime.fromisoformat(row["occurred_at"]) if row else None

    def next_cycle_number(self) -> int:
        row = self._conn.execute("SELECT MAX(cycle) AS c FROM journal").fetchone()
        return int((row["c"] or 0)) + 1

    # -- Ledger (Details in economy/ledger.py) ----------------------------

    def add_ledger_entry(
        self, kind: str, category: str, amount_usd: float, note: str = "", meta: Any = None
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO ledger(occurred_at, kind, category, amount_usd, note, meta) "
                "VALUES(?,?,?,?,?,?)",
                (
                    _now(),
                    kind,
                    category,
                    float(amount_usd),
                    note,
                    json.dumps(meta, ensure_ascii=False, default=str) if meta else None,
                ),
            )

    def ledger_sum(self, kind: str | None = None) -> float:
        if kind:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) AS s FROM ledger WHERE kind=?", (kind,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) AS s FROM ledger"
            ).fetchone()
        return float(row["s"])

    def ledger_sum_excluding(self, kind: str, category: str | Sequence[str]) -> float:
        """Summe einer Art ohne bestimmte Kategorien.

        Gebraucht, um das Geld des Betreibers von dem zu trennen, was der
        Agent selbst verdient hat.
        """
        ausser = [category] if isinstance(category, str) else list(category)
        platzhalter = ",".join("?" for _ in ausser)
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) AS s FROM ledger "
            f"WHERE kind=? AND category NOT IN ({platzhalter})",
            (kind, *ausser),
        ).fetchone()
        return float(row["s"])

    def ledger_entries(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
