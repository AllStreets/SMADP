"""Per-verdict refresh state, stored in a separate SQLite table.

Verdicts are JSON files (`catalog/verdicts/<a>__<b>.json`), so we cannot ALTER a
SQL row. Instead, refresh metadata lives in `<cache_dir>/refresh.db` alongside
the queue.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Final

import structlog

from smadp.config import Config, load_config
from smadp.refresh.queue import _connect
from smadp.refresh.queue import _ensure_schema as _ensure_queue_schema
from smadp.schemas.refresh import RefreshState, RefreshTrigger

log = structlog.get_logger(__name__)

_STATE_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS refresh_state (
    verdict_id TEXT PRIMARY KEY,
    last_trigger TEXT NOT NULL,
    last_evaluated_at TEXT NOT NULL,
    evaluation_count INTEGER NOT NULL DEFAULT 0
);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    _ensure_queue_schema(conn)
    conn.executescript(_STATE_SCHEMA_SQL)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_state(*, verdict_id: str, config: Config | None = None) -> RefreshState | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM refresh_state WHERE verdict_id = ?", (verdict_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return RefreshState(
            verdict_id=row["verdict_id"],
            last_trigger=RefreshTrigger(row["last_trigger"]),
            last_evaluated_at=_from_iso(row["last_evaluated_at"]),
            evaluation_count=int(row["evaluation_count"]),
        )
    finally:
        conn.close()


def upsert_state(
    *,
    verdict_id: str,
    trigger: RefreshTrigger,
    evaluated_at: datetime,
    config: Config | None = None,
) -> None:
    cfg = config or load_config()
    iso = _iso(evaluated_at)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE;")
        try:
            conn.execute(
                "INSERT INTO refresh_state"
                " (verdict_id, last_trigger, last_evaluated_at, evaluation_count)"
                " VALUES (?, ?, ?, 1)"
                " ON CONFLICT(verdict_id) DO UPDATE SET"
                "   last_trigger = excluded.last_trigger,"
                "   last_evaluated_at = excluded.last_evaluated_at,"
                "   evaluation_count = refresh_state.evaluation_count + 1",
                (verdict_id, trigger.value, iso),
            )
            conn.execute("COMMIT;")
        except BaseException:
            conn.execute("ROLLBACK;")
            raise
        log.info("refresh.state.upserted", verdict_id=verdict_id, trigger=trigger.value)
    finally:
        conn.close()


__all__ = ["get_state", "upsert_state"]
