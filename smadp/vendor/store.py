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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import structlog

from smadp.config import Config, load_config
from smadp.schemas.dispute import (
    Dispute,
    DisputeDecision,
    DisputeStatus,
    RequestedOutcome,
)
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
CREATE TABLE IF NOT EXISTS disputes (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    verdict_id TEXT NOT NULL,
    vendor_user_id TEXT NOT NULL,
    argument_md TEXT NOT NULL,
    requested_outcome TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_rationale_md TEXT,
    filed_at TEXT NOT NULL,
    triaged_at TEXT,
    resolved_at TEXT,
    sla_breached_at TEXT
);
CREATE INDEX IF NOT EXISTS disputes_verdict
    ON disputes(workspace_id, verdict_id, status);
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
                "SELECT * FROM vendor_claims WHERE workspace_id = ? ORDER BY created_at DESC",
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
                raise KeyError(f"vendor claim {claim_id!r} is not pending or does not exist")
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
                raise KeyError(f"vendor claim {claim_id!r} already revoked or unknown")
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


_BUSINESS_DAYS_SLA: Final[int] = 5


def _generate_dispute_id(now: datetime) -> str:
    ts = now.strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"dsp_{ts}_{suffix}"


def _add_business_days(start: datetime, days: int) -> datetime:
    """Add N business days (Mon-Fri); skips weekends, ignores holidays."""
    result = start
    added = 0
    while added < days:
        result = result + timedelta(days=1)
        if result.weekday() < 5:  # Mon=0..Fri=4
            added += 1
    return result


_VALID_TRANSITIONS: Final[dict[tuple[DisputeStatus, DisputeDecision], DisputeStatus]] = {
    (DisputeStatus.TRIAGE, DisputeDecision.SPAM): DisputeStatus.SPAM,
    (DisputeStatus.TRIAGE, DisputeDecision.SUBSTANTIVE): DisputeStatus.PENDING_REVIEW,
    (DisputeStatus.PENDING_REVIEW, DisputeDecision.REEVAL): DisputeStatus.RESOLVED_REEVAL,
    (DisputeStatus.PENDING_REVIEW, DisputeDecision.STANDS): DisputeStatus.RESOLVED_STANDS,
}


def _row_to_dispute(row: sqlite3.Row) -> Dispute:
    return Dispute(
        id=row["id"],
        workspace_id=row["workspace_id"],
        verdict_id=row["verdict_id"],
        vendor_user_id=row["vendor_user_id"],
        argument_md=row["argument_md"],
        requested_outcome=RequestedOutcome(row["requested_outcome"]),
        status=DisputeStatus(row["status"]),
        decision_rationale_md=row["decision_rationale_md"],
        filed_at=_from_iso(row["filed_at"]),
        triaged_at=_from_iso(row["triaged_at"]),
        resolved_at=_from_iso(row["resolved_at"]),
        sla_breached_at=_from_iso(row["sla_breached_at"]),
    )


def file_dispute(
    *,
    workspace_id: str,
    verdict_id: str,
    vendor_user_id: str,
    argument_md: str,
    requested_outcome: RequestedOutcome,
    config: Config | None = None,
) -> Dispute:
    cfg = config or load_config()
    now = utcnow()
    dispute_id = _generate_dispute_id(now)
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO disputes"
                "(id, workspace_id, verdict_id, vendor_user_id, argument_md,"
                " requested_outcome, status, decision_rationale_md,"
                " filed_at, triaged_at, resolved_at, sla_breached_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'triage', NULL, ?, NULL, NULL, NULL)",
                (
                    dispute_id,
                    workspace_id,
                    verdict_id,
                    vendor_user_id,
                    argument_md,
                    requested_outcome.value,
                    now_iso,
                ),
            )
        log.info(
            "vendor.dispute.filed",
            workspace_id=workspace_id,
            verdict_id=verdict_id,
            dispute_id=dispute_id,
        )
        return get_dispute(dispute_id=dispute_id, config=cfg)
    finally:
        conn.close()


def get_dispute(*, dispute_id: str, config: Config | None = None) -> Dispute:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown dispute: {dispute_id!r}")
        return _row_to_dispute(row)
    finally:
        conn.close()


def list_disputes(
    *,
    workspace_id: str,
    verdict_id: str | None = None,
    config: Config | None = None,
) -> list[Dispute]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        if verdict_id is None:
            cur = conn.execute(
                "SELECT * FROM disputes WHERE workspace_id = ? ORDER BY filed_at DESC",
                (workspace_id,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM disputes WHERE workspace_id = ? AND verdict_id = ?"
                " ORDER BY filed_at DESC",
                (workspace_id, verdict_id),
            )
        return [_row_to_dispute(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_dispute_status(
    *,
    dispute_id: str,
    decision: DisputeDecision,
    rationale_md: str | None,
    config: Config | None = None,
) -> Dispute:
    cfg = config or load_config()
    current = get_dispute(dispute_id=dispute_id, config=cfg)
    target = _VALID_TRANSITIONS.get((current.status, decision))
    if target is None:
        raise ValueError(f"invalid dispute transition: {current.status.value} → {decision.value}")
    if target in {DisputeStatus.RESOLVED_REEVAL, DisputeStatus.RESOLVED_STANDS}:
        if not rationale_md or not rationale_md.strip():
            raise ValueError("rationale_md required for resolution")
    now = utcnow()
    triaged_at = current.triaged_at
    sla_breached_at = current.sla_breached_at
    resolved_at = current.resolved_at
    if current.status == DisputeStatus.TRIAGE:
        triaged_at = now
        if target == DisputeStatus.PENDING_REVIEW:
            sla_breached_at = _add_business_days(now, _BUSINESS_DAYS_SLA)
        if target == DisputeStatus.SPAM:
            resolved_at = now
    elif target in {DisputeStatus.RESOLVED_REEVAL, DisputeStatus.RESOLVED_STANDS}:
        resolved_at = now

    triaged_iso = (
        triaged_at.isoformat(timespec="seconds").replace("+00:00", "Z") if triaged_at else None
    )
    sla_iso = (
        sla_breached_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        if sla_breached_at
        else None
    )
    resolved_iso = (
        resolved_at.isoformat(timespec="seconds").replace("+00:00", "Z") if resolved_at else None
    )

    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                (
                    "UPDATE disputes SET status = ?, "
                    "decision_rationale_md = COALESCE(?, decision_rationale_md), "
                    "triaged_at = ?, sla_breached_at = ?, resolved_at = ? "
                    "WHERE id = ?"
                ),
                (target.value, rationale_md, triaged_iso, sla_iso, resolved_iso, dispute_id),
            )
        log.info(
            "vendor.dispute.transitioned",
            dispute_id=dispute_id,
            from_status=current.status.value,
            to_status=target.value,
            decision=decision.value,
        )
        return get_dispute(dispute_id=dispute_id, config=cfg)
    finally:
        conn.close()


__all__ = [
    "create_claim",
    "file_dispute",
    "find_verified_claim",
    "get_claim",
    "get_dispute",
    "list_claims",
    "list_disputes",
    "list_responses",
    "mark_claim_verified",
    "post_response",
    "revoke_claim",
    "update_dispute_status",
]
