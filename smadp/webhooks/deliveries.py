"""SQLite-backed webhook_deliveries queue.

Lives in the same DB file as ``smadp/webhooks/store.py`` (subscriptions),
namely ``<cache_dir>/webhooks.db``. ``BEGIN IMMEDIATE`` serializes writes;
the ``status`` state machine is ``pending → running → {delivered, pending,
failed, exhausted}``.

Time is read via the module-level ``_now()`` helper so tests can monkeypatch it.
"""

from __future__ import annotations

import secrets
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Final

import structlog

from smadp.config import Config, load_config
from smadp.schemas.webhooks import DeliveryStatus, EventType, WebhookDelivery
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)


_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    body BLOB NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','running','delivered','failed','exhausted')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    headers_overlay TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS webhook_deliveries_pending
    ON webhook_deliveries(status, next_attempt_at);
"""


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "webhooks.db"


def _connect(config: Config) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(config), isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(webhook_deliveries)")}
    if "headers_overlay" not in cols:
        conn.execute(
            "ALTER TABLE webhook_deliveries ADD COLUMN headers_overlay TEXT NOT NULL DEFAULT '{}'"
        )


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


def _now() -> datetime:
    """Indirection so tests can monkeypatch deliveries._now."""
    return utcnow()


def _isoformat(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _generate_delivery_id(now: datetime) -> str:
    ts = now.strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"wd_{ts}_{suffix}"


def _row_to_delivery(row: sqlite3.Row) -> WebhookDelivery:
    return WebhookDelivery(
        id=row["id"],
        subscription_id=row["subscription_id"],
        event_id=row["event_id"],
        event_type=EventType(row["event_type"]),
        body=bytes(row["body"]),
        status=DeliveryStatus(row["status"]),
        attempts=int(row["attempts"]),
        next_attempt_at=datetime.fromisoformat(row["next_attempt_at"].replace("Z", "+00:00")),
        last_error=row["last_error"],
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        delivered_at=(
            datetime.fromisoformat(row["delivered_at"].replace("Z", "+00:00"))
            if row["delivered_at"]
            else None
        ),
        headers_overlay=json.loads(row["headers_overlay"]),
    )


def enqueue(
    *,
    subscription_id: str,
    event_id: str,
    event_type: EventType,
    body: bytes,
    headers_overlay: dict[str, str] | None = None,
    config: Config | None = None,
) -> str:
    """Insert a pending delivery row; return its id. ``next_attempt_at = now``."""
    cfg = config or load_config()
    now = _now()
    delivery_id = _generate_delivery_id(now)
    overlay_json = json.dumps(headers_overlay or {}, sort_keys=True)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO webhook_deliveries"
                "(id, subscription_id, event_id, event_type, body, status, attempts,"
                " next_attempt_at, last_error, created_at, delivered_at, headers_overlay)"
                " VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, NULL, ?)",
                (
                    delivery_id,
                    subscription_id,
                    event_id,
                    event_type.value,
                    body,
                    _isoformat(now),
                    _isoformat(now),
                    overlay_json,
                ),
            )
        log.info(
            "webhooks.delivery.enqueued",
            delivery_id=delivery_id,
            subscription_id=subscription_id,
            event_id=event_id,
            event_type=event_type.value,
        )
        return delivery_id
    finally:
        conn.close()


def iter_all(*, config: Config | None = None) -> Iterator[WebhookDelivery]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM webhook_deliveries ORDER BY rowid ASC")
        for row in cur.fetchall():
            yield _row_to_delivery(row)
    finally:
        conn.close()


def claim_pending(*, config: Config | None = None) -> WebhookDelivery | None:
    """Atomically claim the oldest pending row whose ``next_attempt_at <= now``.

    Marks the row ``running`` and bumps ``attempts``. Returns the row, or
    ``None`` if no eligible row exists. Two concurrent workers cannot
    return the same row (``BEGIN IMMEDIATE`` serializes the SELECT+UPDATE).
    """
    cfg = config or load_config()
    now = _now()
    now_iso = _isoformat(now)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "SELECT id FROM webhook_deliveries"
                " WHERE status = 'pending' AND next_attempt_at <= ?"
                " ORDER BY next_attempt_at ASC, id ASC LIMIT 1",
                (now_iso,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            delivery_id = row["id"]
            conn.execute(
                "UPDATE webhook_deliveries"
                " SET status = 'running', attempts = attempts + 1"
                " WHERE id = ? AND status = 'pending'",
                (delivery_id,),
            )
            cur = conn.execute("SELECT * FROM webhook_deliveries WHERE id = ?", (delivery_id,))
            return _row_to_delivery(cur.fetchone())
    finally:
        conn.close()


def mark_delivered(*, delivery_id: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    now_iso = _isoformat(_now())
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE webhook_deliveries"
                " SET status = 'delivered', delivered_at = ?, last_error = NULL"
                " WHERE id = ?",
                (now_iso, delivery_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown delivery: {delivery_id!r}")
        log.info("webhooks.delivery.delivered", delivery_id=delivery_id)
    finally:
        conn.close()


def mark_failed(*, delivery_id: str, error: str, config: Config | None = None) -> None:
    """Terminal: 4xx response — no retry."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE webhook_deliveries SET status = 'failed', last_error = ? WHERE id = ?",
                (error, delivery_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown delivery: {delivery_id!r}")
        log.info("webhooks.delivery.failed", delivery_id=delivery_id, error=error)
    finally:
        conn.close()


def mark_exhausted(*, delivery_id: str, error: str, config: Config | None = None) -> None:
    """Terminal: retry budget exceeded."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE webhook_deliveries SET status = 'exhausted', last_error = ? WHERE id = ?",
                (error, delivery_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown delivery: {delivery_id!r}")
        log.info("webhooks.delivery.exhausted", delivery_id=delivery_id, error=error)
    finally:
        conn.close()


def reschedule_pending(
    *,
    delivery_id: str,
    next_attempt_at: datetime,
    error: str,
    config: Config | None = None,
) -> None:
    """Re-arm a running row as pending with a future attempt time."""
    cfg = config or load_config()
    next_iso = _isoformat(next_attempt_at)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE webhook_deliveries"
                " SET status = 'pending', next_attempt_at = ?, last_error = ?"
                " WHERE id = ?",
                (next_iso, error, delivery_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown delivery: {delivery_id!r}")
        log.info(
            "webhooks.delivery.rescheduled",
            delivery_id=delivery_id,
            next_attempt_at=next_iso,
            error=error,
        )
    finally:
        conn.close()


__all__ = [
    "claim_pending",
    "enqueue",
    "iter_all",
    "mark_delivered",
    "mark_exhausted",
    "mark_failed",
    "reschedule_pending",
]
