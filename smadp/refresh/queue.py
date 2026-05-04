"""SQLite-backed refresh FIFO queue with 5-minute claim lease + reaper."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

import structlog

from smadp.config import Config, load_config
from smadp.schemas.refresh import RefreshQueueItem, RefreshTrigger
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)

_CLAIM_LEASE_SECONDS: Final[int] = 300

_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS refresh_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verdict_id TEXT NOT NULL,
    trigger TEXT NOT NULL,
    trigger_detail TEXT NOT NULL DEFAULT '{}',
    enqueued_at TEXT NOT NULL,
    claimed_at TEXT,
    done_at TEXT
);
CREATE INDEX IF NOT EXISTS refresh_queue_pending
    ON refresh_queue(claimed_at, enqueued_at);
CREATE INDEX IF NOT EXISTS refresh_queue_done
    ON refresh_queue(done_at);
"""


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "refresh.db"


def _connect(config: Config) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(config), isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _row_to_item(row: sqlite3.Row) -> RefreshQueueItem:
    return RefreshQueueItem(
        id=row["id"],
        verdict_id=row["verdict_id"],
        trigger=RefreshTrigger(row["trigger"]),
        trigger_detail=json.loads(row["trigger_detail"]),
        enqueued_at=_from_iso(row["enqueued_at"]),  # type: ignore[arg-type]
        claimed_at=_from_iso(row["claimed_at"]),
        done_at=_from_iso(row["done_at"]),
    )


def enqueue(
    *,
    verdict_id: str,
    trigger: RefreshTrigger,
    trigger_detail: dict[str, Any] | None = None,
    config: Config | None = None,
) -> RefreshQueueItem:
    cfg = config or load_config()
    detail_json = json.dumps(trigger_detail or {}, sort_keys=True)
    enq = _iso(utcnow())
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "INSERT INTO refresh_queue (verdict_id, trigger, trigger_detail, enqueued_at)"
                " VALUES (?, ?, ?, ?) RETURNING id",
                (verdict_id, trigger.value, detail_json, enq),
            )
            row = cur.fetchone()
            assert row is not None
            new_id = int(row[0])
        log.info(
            "refresh.queue.enqueued",
            verdict_id=verdict_id,
            trigger=trigger.value,
            id=new_id,
        )
        return RefreshQueueItem(
            id=new_id,
            verdict_id=verdict_id,
            trigger=trigger,
            trigger_detail=trigger_detail or {},
            enqueued_at=_from_iso(enq),  # type: ignore[arg-type]
            claimed_at=None,
            done_at=None,
        )
    finally:
        conn.close()


def list_pending(*, config: Config | None = None) -> list[RefreshQueueItem]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM refresh_queue WHERE done_at IS NULL"
            " ORDER BY enqueued_at ASC, id ASC"
        )
        return [_row_to_item(r) for r in cur.fetchall()]
    finally:
        conn.close()


__all__ = ["enqueue", "list_pending"]
