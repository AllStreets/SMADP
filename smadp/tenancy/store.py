"""SQLite-backed workspace + member store.

Follows the pattern used by ``smadp/sandbox/queue.py``: WAL mode, foreign
keys on, ``BEGIN IMMEDIATE`` for serialized writes, ISO-8601 ``Z`` strings
for timestamps. The DB lives at ``<cache_dir>/tenancy.db``.
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
from smadp.schemas.tenancy import Plan, Workspace
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)


_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    plan TEXT NOT NULL CHECK(plan IN ('public','private')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('viewer','editor','admin','owner')),
    PRIMARY KEY (workspace_id, user_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workspace_members_user
    ON workspace_members(user_id);
"""


def _db_path(config: Config) -> Path:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config.cache_dir / "tenancy.db"


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


def _generate_workspace_id() -> str:
    """Sortable, case-insensitive base32-ish id: ws_<8 uppercase alphanum>."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "ws_" + "".join(secrets.choice(alphabet) for _ in range(8))


def _row_to_workspace(row: sqlite3.Row) -> Workspace:
    return Workspace(
        id=row["id"],
        name=row["name"],
        plan=Plan(row["plan"]),
        created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
    )


def create_workspace(
    *,
    name: str,
    plan: Plan,
    config: Config | None = None,
) -> Workspace:
    cfg = config or load_config()
    ws_id = _generate_workspace_id()
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO workspaces(id, name, plan, created_at) VALUES (?, ?, ?, ?)",
                (ws_id, name, plan.value, now_iso),
            )
        log.info("tenancy.workspace.created", workspace_id=ws_id, plan=plan.value)
        return get_workspace(ws_id, config=cfg)
    finally:
        conn.close()


def get_workspace(workspace_id: str, *, config: Config | None = None) -> Workspace:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"No workspace with id {workspace_id!r}")
        return _row_to_workspace(row)
    finally:
        conn.close()


def list_workspaces(*, config: Config | None = None) -> list[Workspace]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM workspaces ORDER BY rowid ASC")
        return [_row_to_workspace(r) for r in cur.fetchall()]
    finally:
        conn.close()


def delete_workspace(workspace_id: str, *, config: Config | None = None) -> None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            cur = conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
            if cur.rowcount == 0:
                raise KeyError(f"No workspace with id {workspace_id!r}")
        log.info("tenancy.workspace.deleted", workspace_id=workspace_id)
    finally:
        conn.close()


__all__ = [
    "create_workspace",
    "delete_workspace",
    "get_workspace",
    "list_workspaces",
]
