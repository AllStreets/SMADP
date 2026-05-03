"""Append-only signed-event journal (the transparency log).

Every state change in v2-D writes a signed event here. Each event chains
to the previous via ``prev_hash = sha256(prev.signature)``, so a single
mutation breaks the chain at every following row. The chain root is the
genesis hash ``sha256:0...0`` (64 zeros).

Signatures are Ed25519 over a canonical-JSON encoding of
``{id, event_type, payload, ts, prev_hash}`` — we never sign anything
that isn't reproducible byte-for-byte.

Storage lives at ``<cache_dir>/transparency.db``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config, load_config
from smadp.schemas.transparency import SignedEvent
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)

GENESIS_PREV_HASH: Final[str] = "sha256:" + "0" * 64

_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS signed_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    ts TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    rekor_uuid TEXT
);
CREATE INDEX IF NOT EXISTS signed_events_event_type
    ON signed_events(event_type);
CREATE INDEX IF NOT EXISTS signed_events_rekor_pending
    ON signed_events(rekor_uuid)
    WHERE rekor_uuid IS NULL;
"""


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "transparency.db"


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


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _canonical_signing_input(ev: SignedEvent) -> bytes:
    """Bytes that get signed. Stable, sort_keys, no whitespace."""
    blob = {
        "id": ev.id,
        "event_type": ev.event_type,
        "payload": ev.payload,
        "ts": ev.ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "prev_hash": ev.prev_hash,
    }
    return json.dumps(
        blob, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _hash_signature(hex_sig: str) -> str:
    """Hash a hex-encoded signature → ``sha256:<hex>`` for the next prev_hash."""
    return "sha256:" + hashlib.sha256(bytes.fromhex(hex_sig)).hexdigest()


def append_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    signing_key: Ed25519PrivateKey,
    config: Config | None = None,
) -> SignedEvent:
    """Append a signed event to the journal; return the persisted ``SignedEvent``."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "SELECT signature FROM signed_events ORDER BY id DESC LIMIT 1"
            )
            tail = cur.fetchone()
            prev_hash = _hash_signature(tail["signature"]) if tail else GENESIS_PREV_HASH

            cur = conn.execute(
                "INSERT INTO signed_events"
                "(event_type, payload, ts, prev_hash, signature) "
                "VALUES (?, ?, ?, ?, ?)",
                (event_type, _canonical_payload(payload).decode("utf-8"),
                 utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                 prev_hash, ""),  # placeholder signature
            )
            new_id = cur.lastrowid
            assert new_id is not None
            cur = conn.execute("SELECT * FROM signed_events WHERE id = ?", (new_id,))
            row = cur.fetchone()

            ev_unsigned = SignedEvent(
                id=row["id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload"]),
                ts=datetime.fromisoformat(row["ts"].replace("Z", "+00:00")),
                prev_hash=row["prev_hash"],
                signature="00",  # placeholder for schema validation
                rekor_uuid=None,
            )
            sig_bytes = signing_key.sign(_canonical_signing_input(ev_unsigned))
            sig_hex = sig_bytes.hex()
            conn.execute(
                "UPDATE signed_events SET signature = ? WHERE id = ?",
                (sig_hex, new_id),
            )

        log.info(
            "transparency.event.appended",
            event_id=new_id,
            event_type=event_type,
            prev_hash=prev_hash,
        )
        return SignedEvent(
            id=new_id,
            event_type=event_type,
            payload=payload,
            ts=ev_unsigned.ts,
            prev_hash=prev_hash,
            signature=sig_hex,
            rekor_uuid=None,
        )
    finally:
        conn.close()


__all__ = [
    "GENESIS_PREV_HASH",
    "append_event",
]
