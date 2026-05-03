"""SQLite-backed vendor store: claims, responses, disputes.

DB lives at ``<cache_dir>/vendor.db`` (WAL, BEGIN IMMEDIATE).
Tokens are stored in plaintext — they are server-generated nonces and
verifying still requires control of the corresponding repo/DNS/inbox.
"""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Final

import structlog

from smadp.config import Config, load_config
from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimStatus,
    VendorClaim,
    VendorResponse,
)
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)


_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS vendor_claims (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    vendor_user_id TEXT NOT NULL,
    method TEXT NOT NULL,
    token TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_url TEXT,
    created_at TEXT NOT NULL,
    granted_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS vendor_claims_workspace
    ON vendor_claims(workspace_id, agent_id);
CREATE INDEX IF NOT EXISTS vendor_claims_user
    ON vendor_claims(workspace_id, vendor_user_id, agent_id, status);
CREATE TABLE IF NOT EXISTS vendor_responses (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    verdict_id TEXT NOT NULL,
    vendor_user_id TEXT NOT NULL,
    body_md TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS vendor_responses_verdict
    ON vendor_responses(workspace_id, verdict_id);
"""


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "vendor.db"


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


def _now_iso() -> str:
    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


def _from_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _generate_claim_id() -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "vc_" + "".join(secrets.choice(alphabet) for _ in range(8))


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _row_to_claim(row: sqlite3.Row) -> VendorClaim:
    return VendorClaim(
        id=row["id"],
        workspace_id=row["workspace_id"],
        agent_id=row["agent_id"],
        vendor_user_id=row["vendor_user_id"],
        method=ClaimMethod(row["method"]),
        token=row["token"],
        status=ClaimStatus(row["status"]),
        evidence_url=row["evidence_url"],
        created_at=_from_iso(row["created_at"]),
        granted_at=_from_iso(row["granted_at"]),
        revoked_at=_from_iso(row["revoked_at"]),
    )


def create_claim(
    *,
    workspace_id: str,
    agent_id: str,
    vendor_user_id: str,
    method: ClaimMethod,
    evidence_url: str | None,
    config: Config | None = None,
) -> VendorClaim:
    cfg = config or load_config()
    claim_id = _generate_claim_id()
    token = _generate_token()
    now_iso = _now_iso()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO vendor_claims"
                "(id, workspace_id, agent_id, vendor_user_id, method, token,"
                " status, evidence_url, created_at, granted_at, revoked_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL, NULL)",
                (
                    claim_id,
                    workspace_id,
                    agent_id,
                    vendor_user_id,
                    method.value,
                    token,
                    evidence_url,
                    now_iso,
                ),
            )
        log.info(
            "vendor.claim.created",
            workspace_id=workspace_id,
            agent_id=agent_id,
            claim_id=claim_id,
            method=method.value,
        )
        return get_claim(claim_id=claim_id, config=cfg)
    finally:
        conn.close()


def get_claim(*, claim_id: str, config: Config | None = None) -> VendorClaim:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM vendor_claims WHERE id = ?", (claim_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown vendor claim: {claim_id!r}")
        return _row_to_claim(row)
    finally:
        conn.close()


def list_claims(
    *,
    workspace_id: str,
    agent_id: str | None = None,
    config: Config | None = None,
) -> list[VendorClaim]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        if agent_id is None:
            cur = conn.execute(
                "SELECT * FROM vendor_claims WHERE workspace_id = ?"
                " ORDER BY created_at DESC",
                (workspace_id,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM vendor_claims WHERE workspace_id = ? AND agent_id = ?"
                " ORDER BY created_at DESC",
                (workspace_id, agent_id),
            )
        return [_row_to_claim(r) for r in cur.fetchall()]
    finally:
        conn.close()


def mark_claim_verified(*, claim_id: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    now_iso = _now_iso()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE vendor_claims SET status='verified', granted_at=?"
                " WHERE id = ? AND status='pending'",
                (now_iso, claim_id),
            )
            if cur.rowcount == 0:
                raise KeyError(
                    f"vendor claim {claim_id!r} is not pending or does not exist"
                )
        log.info("vendor.claim.verified", claim_id=claim_id)
    finally:
        conn.close()


def revoke_claim(*, claim_id: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    now_iso = _now_iso()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE vendor_claims SET status='revoked', revoked_at=?"
                " WHERE id = ? AND status != 'revoked'",
                (now_iso, claim_id),
            )
            if cur.rowcount == 0:
                raise KeyError(
                    f"vendor claim {claim_id!r} already revoked or unknown"
                )
        log.info("vendor.claim.revoked", claim_id=claim_id)
    finally:
        conn.close()


def find_verified_claim(
    *,
    workspace_id: str,
    vendor_user_id: str,
    agent_id: str,
    config: Config | None = None,
) -> VendorClaim | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM vendor_claims"
            " WHERE workspace_id = ? AND vendor_user_id = ?"
            " AND agent_id = ? AND status = 'verified'"
            " ORDER BY granted_at DESC LIMIT 1",
            (workspace_id, vendor_user_id, agent_id),
        )
        row = cur.fetchone()
        return _row_to_claim(row) if row else None
    finally:
        conn.close()


def _generate_response_id(now: datetime) -> str:
    ts = now.strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"vr_{ts}_{suffix}"


def _row_to_response(row: sqlite3.Row) -> VendorResponse:
    return VendorResponse(
        id=row["id"],
        workspace_id=row["workspace_id"],
        verdict_id=row["verdict_id"],
        vendor_user_id=row["vendor_user_id"],
        body_md=row["body_md"],
        created_at=_from_iso(row["created_at"]),
    )


def post_response(
    *,
    workspace_id: str,
    verdict_id: str,
    vendor_user_id: str,
    body_md: str,
    config: Config | None = None,
) -> VendorResponse:
    cfg = config or load_config()
    now = utcnow()
    response_id = _generate_response_id(now)
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO vendor_responses"
                "(id, workspace_id, verdict_id, vendor_user_id, body_md, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (response_id, workspace_id, verdict_id, vendor_user_id, body_md, now_iso),
            )
        log.info(
            "vendor.response.posted",
            workspace_id=workspace_id,
            verdict_id=verdict_id,
            response_id=response_id,
        )
        return VendorResponse(
            id=response_id,
            workspace_id=workspace_id,
            verdict_id=verdict_id,
            vendor_user_id=vendor_user_id,
            body_md=body_md,
            created_at=_from_iso(now_iso),
        )
    finally:
        conn.close()


def list_responses(
    *,
    workspace_id: str,
    verdict_id: str,
    config: Config | None = None,
) -> list[VendorResponse]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM vendor_responses"
            " WHERE workspace_id = ? AND verdict_id = ?"
            " ORDER BY created_at ASC",
            (workspace_id, verdict_id),
        )
        return [_row_to_response(r) for r in cur.fetchall()]
    finally:
        conn.close()


__all__ = [
    "create_claim",
    "find_verified_claim",
    "get_claim",
    "list_claims",
    "list_responses",
    "mark_claim_verified",
    "post_response",
    "revoke_claim",
]
