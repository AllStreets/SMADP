"""SQLite-backed job queue for the Sandbox Validator.

Why SQLite, not Celery/Redis/RabbitMQ:

* Zero infra. The catalog repo is the source of truth; the queue is
  per-host, per-process state. A single ``BEGIN IMMEDIATE`` transaction
  serializes worker pulls cleanly without an external broker.
* Auditability. The DB lives at ``<cache_dir>/sandbox-queue.db`` and can be
  inspected with the ``sqlite3`` CLI; every state transition is timestamped.
* Horizontal scale (later) is achieved by adding hosts that pull from a
  *shared catalog* via git remote — not by sharing the queue.

The queue is the ONLY entry point for sandbox runs. It enforces:

* slug normalization + alphabetization (canonical pair identity)
* scenario existence (built-in scenarios only in v1)
* secret hygiene (rejects anything that looks like a real key)

The runner (:mod:`smadp.sandbox.runner`) is what actually executes runs;
this module never touches a container.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

import structlog

from smadp.config import Config, load_config
from smadp.sandbox.binding import bind_scenario_to_pair, load_adapter_capabilities
from smadp.sandbox.policy import (
    UnsafeSecretError,
    looks_like_real_secret,
)
from smadp.sandbox.scenarios import list_builtin_scenarios, load_scenario
from smadp.schemas.verdict import SandboxRun
from smadp.utils.slug import normalize_slug, sort_pair
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)

RunState = Literal["pending", "running", "completed", "failed"]

_VALID_STATES: Final[frozenset[str]] = frozenset({"pending", "running", "completed", "failed"})

_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    slug_a TEXT NOT NULL,
    slug_b TEXT NOT NULL,
    scenario TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    transcript_path TEXT,
    outcome TEXT,
    error TEXT,
    role_a TEXT,
    role_b TEXT,
    participants_json TEXT       -- '[{"role": "...", "slug": "..."}, ...]' for N-ary
);
CREATE INDEX IF NOT EXISTS runs_state_created
    ON runs(state, created_at);
CREATE INDEX IF NOT EXISTS runs_pair
    ON runs(slug_a, slug_b);
"""


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "sandbox-queue.db"


def _connect(config: Config) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(config), isolation_level=None, timeout=30)
    # WAL gives concurrent readers + a single writer — perfect for one worker.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    # Additive migration for DBs created before role_a/role_b/participants_json
    # existed. Each column is TEXT and nullable so a no-op backfill is safe.
    cur = conn.execute("PRAGMA table_info(runs)")
    existing_cols = {row[1] for row in cur.fetchall()}
    for col in ("role_a", "role_b", "participants_json"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")


@contextmanager
def _transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[None]:
    """Atomic BEGIN IMMEDIATE / COMMIT context manager."""
    conn.execute("BEGIN IMMEDIATE;" if immediate else "BEGIN;")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def _generate_run_id(slug_a: str, slug_b: str) -> str:
    """Compact, sortable, collision-resistant run id.

    Format: ``sb_<YYYYMMDDhhmmss>_<a>__<b>_<6hex>``
    """
    ts = utcnow().strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"sb_{ts}_{slug_a}__{slug_b}_{suffix}"


# ---------------------------------------------------------------------------
# Row → SandboxRun
# ---------------------------------------------------------------------------


def _parse_dt(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _row_to_sandbox_run(row: sqlite3.Row) -> SandboxRun:
    """Convert a DB row to the public ``SandboxRun`` Pydantic model.

    The ``SandboxRun`` schema (see ``smadp/schemas/verdict.py``) is what the
    Verdict object embeds into the catalog — so the queue's external surface
    speaks in that type rather than in raw rows.
    """
    started = _parse_dt(row["started_at"]) or _parse_dt(row["created_at"])
    assert started is not None  # created_at is NOT NULL
    outcome = row["outcome"]
    if outcome is None:
        # Schema requires SandboxOutcome; queue maps queue-state → outcome.
        if row["state"] in {"pending", "running"}:
            outcome = "inconclusive"
        elif row["state"] == "failed":
            outcome = "errored"
        else:
            outcome = "inconclusive"
    transcript_ref = row["transcript_path"] or f"queue://run/{row['id']}"
    return SandboxRun(
        run_id=row["id"],
        started_at=started,
        completed_at=_parse_dt(row["completed_at"]),
        outcome=outcome,
        transcript_ref=transcript_ref,
        scenario=row["scenario"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enqueue_sandbox_run(
    slug_a: str,
    slug_b: str,
    scenario: str,
    *,
    config: Config | None = None,
) -> str:
    """Enqueue a sandbox run; return its run id.

    Raises:
        ValueError: invalid slug, unknown scenario.
        UnsafeSecretError: any input contained a real-looking secret.
    """
    cfg = config or load_config()
    a_norm = normalize_slug(slug_a)
    b_norm = normalize_slug(slug_b)
    a_sorted, b_sorted = sort_pair(a_norm, b_norm)

    if scenario not in list_builtin_scenarios():
        raise ValueError(f"Unknown scenario {scenario!r}. Available: {list_builtin_scenarios()}")

    # Defense in depth: even though slugs/scenario should never be a secret,
    # reject if any *input* string smells like a real key. The actual env
    # values are screened again at the runner.
    for v in (slug_a, slug_b, scenario):
        if looks_like_real_secret(v):
            raise UnsafeSecretError("Refusing to enqueue: input contains a real-secret pattern.")

    run_id = _generate_run_id(a_sorted, b_sorted)
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")

    # Capability-based scenario↔adapter binding.
    sc = load_scenario(scenario)
    caps_a = load_adapter_capabilities(a_sorted, config=cfg)
    caps_b = load_adapter_capabilities(b_sorted, config=cfg)
    binding = bind_scenario_to_pair(
        sc,
        slug_a=a_sorted,
        caps_a=caps_a,
        slug_b=b_sorted,
        caps_b=caps_b,
    )

    # Forward-compat: also populate participants_json so the row is shaped
    # like an N-ary row for the rest of the pipeline (Task 3+ readers fall
    # through to slug_a/slug_b when this column is NULL, so legacy rows are
    # still readable — see ``participants_for_row``).
    participants_payload = json.dumps(
        [
            {"role": binding.role_a, "slug": a_sorted},
            {"role": binding.role_b, "slug": b_sorted},
        ],
        separators=(",", ":"),
    )

    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO runs(id, slug_a, slug_b, scenario, state, "
                "created_at, role_a, role_b, participants_json) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
                (
                    run_id,
                    a_sorted,
                    b_sorted,
                    scenario,
                    now_iso,
                    binding.role_a,
                    binding.role_b,
                    participants_payload,
                ),
            )
        log.info(
            "sandbox.queue.enqueued",
            run_id=run_id,
            slug_a=a_sorted,
            slug_b=b_sorted,
            scenario=scenario,
            role_a=binding.role_a,
            role_b=binding.role_b,
        )
        return run_id
    finally:
        conn.close()


def participants_for_row(row: dict[str, Any]) -> list[dict[str, str]]:
    """Decode the participants list (role+slug) for a queue row.

    Prefers the canonical participants_json column. Falls back to the legacy
    slug_a/slug_b/role_a/role_b columns for rows enqueued before the N-ary
    migration. Raises if the legacy columns are present but the role values
    are NULL — that indicates a row enqueued by a pre-binding-aware runner,
    which can't be re-played safely.
    """
    raw = row.get("participants_json")
    if raw:
        decoded = json.loads(raw)
        if not isinstance(decoded, list):
            raise ValueError(
                f"participants_json must decode to a list; got {type(decoded).__name__}"
            )
        return decoded

    role_a = row.get("role_a")
    role_b = row.get("role_b")
    if role_a is None or role_b is None:
        raise ValueError(
            f"queue row id={row.get('id')!r} has no participants_json and "
            f"role_a/role_b are NULL — cannot decode participants for "
            f"slug_a={row.get('slug_a')!r}, slug_b={row.get('slug_b')!r}"
        )
    return [
        {"role": role_a, "slug": row["slug_a"]},
        {"role": role_b, "slug": row["slug_b"]},
    ]


def get_run_status(run_id: str, *, config: Config | None = None) -> SandboxRun:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"No sandbox run with id {run_id!r}")
        return _row_to_sandbox_run(row)
    finally:
        conn.close()


def iter_runs(
    *,
    config: Config | None = None,
    limit: int = 100,
) -> Iterator[SandboxRun]:
    """Iterate runs newest-first up to ``limit`` rows."""
    if limit <= 0 or limit > 10_000:
        raise ValueError(f"limit must be in (0, 10000], got {limit}")
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        for row in cur.fetchall():
            yield _row_to_sandbox_run(row)
    finally:
        conn.close()


def list_pending(*, config: Config | None = None) -> list[SandboxRun]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM runs WHERE state = 'pending' ORDER BY created_at ASC")
        return [_row_to_sandbox_run(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Worker-facing API (called only by runner.py)
# ---------------------------------------------------------------------------


def claim_next_pending(
    *,
    config: Config | None = None,
    scenario: str | None = None,
) -> SandboxRun | None:
    """Atomically transition the oldest pending run to ``running`` and return it.

    Returns ``None`` if no pending runs exist. Uses ``BEGIN IMMEDIATE`` so
    multiple workers on the same DB cannot double-claim.

    ``scenario`` filters the candidate set to rows whose ``scenario`` column
    equals the given value, so a worker started with ``--scenario`` only
    drains its slice of the queue.
    """
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            if scenario is None:
                cur = conn.execute(
                    "SELECT * FROM runs WHERE state = 'pending' ORDER BY created_at ASC LIMIT 1"
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM runs WHERE state = 'pending' AND scenario = ? "
                    "ORDER BY created_at ASC LIMIT 1",
                    (scenario,),
                )
            row = cur.fetchone()
            if row is None:
                return None
            now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
            conn.execute(
                "UPDATE runs SET state='running', started_at=? WHERE id=? AND state='pending'",
                (now_iso, row["id"]),
            )
        # Re-read for accurate started_at.
        cur = conn.execute("SELECT * FROM runs WHERE id = ?", (row["id"],))
        fresh = cur.fetchone()
        return _row_to_sandbox_run(fresh)
    finally:
        conn.close()


def mark_completed(
    run_id: str,
    *,
    outcome: str,
    transcript_path: str,
    config: Config | None = None,
) -> None:
    _update_terminal(
        run_id,
        "completed",
        outcome=outcome,
        transcript_path=transcript_path,
        error=None,
        config=config,
    )


def mark_failed(
    run_id: str,
    *,
    error: str,
    transcript_path: str | None = None,
    config: Config | None = None,
) -> None:
    _update_terminal(
        run_id,
        "failed",
        outcome="errored",
        transcript_path=transcript_path,
        error=error,
        config=config,
    )


def _update_terminal(
    run_id: str,
    state: RunState,
    *,
    outcome: str,
    transcript_path: str | None,
    error: str | None,
    config: Config | None,
) -> None:
    if state not in _VALID_STATES:
        raise ValueError(f"Invalid state {state!r}")
    cfg = config or load_config()
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute(
                "UPDATE runs SET state=?, completed_at=?, outcome=?, transcript_path=?, error=? "
                "WHERE id=? AND state IN ('running','pending')",
                (state, now_iso, outcome, transcript_path, error, run_id),
            )
            if cur.rowcount == 0:
                raise RuntimeError(
                    f"Cannot transition run {run_id!r} to {state!r}: "
                    "row missing or already terminal."
                )
        log.info(
            "sandbox.queue.terminal",
            run_id=run_id,
            state=state,
            outcome=outcome,
            error=error,
        )
    finally:
        conn.close()


def get_raw_row(run_id: str, *, config: Config | None = None) -> dict[str, Any] | None:
    """Return the raw queue row for ``run_id`` as a dict, or None if no such run.

    Exposed because the runner and promotion module need slug+role+transcript
    fields that the public ``SandboxRun`` schema omits.
    """
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _all_rows_for_test(*, config: Config | None = None) -> list[dict[str, Any]]:
    """Test-only helper — returns raw rows as dicts."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM runs ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


__all__ = [
    "RunState",
    "claim_next_pending",
    "enqueue_sandbox_run",
    "get_raw_row",
    "get_run_status",
    "iter_runs",
    "list_pending",
    "mark_completed",
    "mark_failed",
    "participants_for_row",
]
