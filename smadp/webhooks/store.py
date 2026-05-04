"""SQLite-backed subscriptions store with AES-GCM secret-at-rest encryption.

Mirrors the BYOK pattern in ``smadp/tenancy/keys.py``: HKDF over
``SMADP_KEK_MASTER`` with the workspace id as salt; per-row 12-byte nonce.
The DB lives at ``<cache_dir>/webhooks.db``.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Final

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from smadp.config import Config, load_config
from smadp.schemas.webhooks import EventType, IntegrationKind, Subscription
from smadp.tenancy.keys import _derive_dek
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)


_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    url TEXT NOT NULL,
    event_types TEXT NOT NULL,        -- JSON array of EventType values
    active INTEGER NOT NULL,          -- 0/1
    nonce BLOB NOT NULL,
    secret_encrypted BLOB NOT NULL,
    created_at TEXT NOT NULL,
    integration_kind TEXT NOT NULL DEFAULT 'generic',
    integration_config TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS subscriptions_workspace
    ON subscriptions(workspace_id, active);
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
    cols = {row[1] for row in conn.execute("PRAGMA table_info(subscriptions)")}
    if "integration_kind" not in cols:
        conn.execute(
            "ALTER TABLE subscriptions ADD COLUMN integration_kind TEXT NOT NULL DEFAULT 'generic'"
        )
    if "integration_config" not in cols:
        conn.execute(
            "ALTER TABLE subscriptions ADD COLUMN integration_config TEXT NOT NULL DEFAULT '{}'"
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


def _generate_subscription_id() -> str:
    """``sub_<8 uppercase base32-ish>``."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "sub_" + "".join(secrets.choice(alphabet) for _ in range(8))


def _generate_secret() -> str:
    """48 bytes of entropy → urlsafe base64 (~64 chars)."""
    return secrets.token_urlsafe(48)


def _encrypt(plaintext: bytes, *, workspace_id: str) -> tuple[bytes, bytes]:
    dek = _derive_dek(workspace_id)
    aes = AESGCM(dek)
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext, associated_data=workspace_id.encode("utf-8"))
    return nonce, ct


def _decrypt(*, nonce: bytes, ciphertext: bytes, workspace_id: str) -> bytes:
    dek = _derive_dek(workspace_id)
    aes = AESGCM(dek)
    return aes.decrypt(nonce, ciphertext, associated_data=workspace_id.encode("utf-8"))


def _row_to_subscription(row: sqlite3.Row) -> Subscription:
    return Subscription(
        id=row["id"],
        workspace_id=row["workspace_id"],
        url=row["url"],
        event_types=[EventType(v) for v in json.loads(row["event_types"])],
        active=bool(row["active"]),
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        integration_kind=IntegrationKind(row["integration_kind"]),
        integration_config=json.loads(row["integration_config"]),
    )


def create_subscription(
    *,
    workspace_id: str,
    url: str,
    event_types: list[EventType],
    config: Config | None = None,
    integration_kind: IntegrationKind = IntegrationKind.GENERIC,
    integration_config: dict | None = None,
) -> tuple[Subscription, str]:
    """Insert a new subscription; return (subscription, plaintext_secret).

    The plaintext secret is the only chance to read it — store it once
    and surface to the caller (e.g. the API response). The subscription
    object itself never carries the secret.
    """
    cfg = config or load_config()
    sub_id = _generate_subscription_id()
    secret = _generate_secret()
    nonce, encrypted = _encrypt(secret.encode("utf-8"), workspace_id=workspace_id)
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    types_json = json.dumps([t.value for t in event_types], sort_keys=True)
    config_json = json.dumps(integration_config or {}, sort_keys=True)
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO subscriptions"
                "(id, workspace_id, url, event_types, active, nonce,"
                " secret_encrypted, created_at, integration_kind, integration_config)"
                " VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (
                    sub_id,
                    workspace_id,
                    url,
                    types_json,
                    nonce,
                    encrypted,
                    now_iso,
                    integration_kind.value,
                    config_json,
                ),
            )
        log.info(
            "webhooks.subscription.created",
            workspace_id=workspace_id,
            subscription_id=sub_id,
            url=url,
            integration_kind=integration_kind.value,
        )
        return (
            Subscription(
                id=sub_id,
                workspace_id=workspace_id,
                url=url,
                event_types=event_types,
                active=True,
                created_at=datetime.fromisoformat(now_iso.replace("Z", "+00:00")),
                integration_kind=integration_kind,
                integration_config=integration_config or {},
            ),
            secret,
        )
    finally:
        conn.close()


def get_subscription(*, subscription_id: str, config: Config | None = None) -> Subscription:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown subscription: {subscription_id!r}")
        return _row_to_subscription(row)
    finally:
        conn.close()


def list_subscriptions(*, workspace_id: str, config: Config | None = None) -> list[Subscription]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM subscriptions WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
        return [_row_to_subscription(r) for r in cur.fetchall()]
    finally:
        conn.close()


def match_subscriptions(
    *,
    workspace_id: str,
    event_type: EventType,
    config: Config | None = None,
) -> list[Subscription]:
    """Active subscriptions for ``workspace_id`` whose event_types contain ``event_type``."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM subscriptions WHERE workspace_id = ? AND active = 1",
            (workspace_id,),
        )
        out: list[Subscription] = []
        for r in cur.fetchall():
            sub = _row_to_subscription(r)
            if event_type in sub.event_types:
                out.append(sub)
        return out
    finally:
        conn.close()


def deactivate_subscription(*, subscription_id: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE subscriptions SET active = 0 WHERE id = ?", (subscription_id,)
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown subscription: {subscription_id!r}")
        log.info("webhooks.subscription.deactivated", subscription_id=subscription_id)
    finally:
        conn.close()


def load_subscription_secret(*, subscription_id: str, config: Config | None = None) -> str:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT workspace_id, nonce, secret_encrypted FROM subscriptions WHERE id = ?",
            (subscription_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown subscription: {subscription_id!r}")
        plain = _decrypt(
            nonce=row["nonce"],
            ciphertext=row["secret_encrypted"],
            workspace_id=row["workspace_id"],
        )
        return plain.decode("utf-8")
    finally:
        conn.close()


__all__ = [
    "create_subscription",
    "deactivate_subscription",
    "get_subscription",
    "list_subscriptions",
    "load_subscription_secret",
    "match_subscriptions",
]
