# SMADP v2-D Plan 1: Foundation (Tenancy + Transparency Log) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the storage and signing primitives that every other v2-D feature depends on: workspaces with role-based access, BYOK signing-key storage encrypted at rest, and an append-only signed-event journal with chain verification.

**Architecture:** Two new sub-packages added to the existing v1 monolith. `smadp.tenancy` owns workspaces, members, RBAC, and BYOK keys; `smadp.transparency` owns the signed-event journal. Both follow v1's SQLite-WAL + `BEGIN IMMEDIATE` pattern (see `smadp/sandbox/queue.py`). Two new FastAPI routers (`/api/workspaces`, `/api/transparency`) and two new CLI commands (`smadp transparency verify`, `smadp transparency export`) round out the surface.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, SQLite (WAL), `cryptography` (Ed25519 + AES-GCM, NEW dep), structlog, pytest, click + Rich.

**Spec reference:** `docs/superpowers/specs/2026-05-03-v2-d-audience-cd-design.md` §5.2, §6.1, §6.2, §8.1, §10.

---

## File structure

**Create:**
- `smadp/schemas/tenancy.py` — Pydantic models: `Workspace`, `Member`, `Role`, `Plan`
- `smadp/schemas/transparency.py` — Pydantic models: `SignedEvent`, `InclusionProof`
- `smadp/tenancy/__init__.py`
- `smadp/tenancy/store.py` — SQLite tables (`workspaces`, `workspace_members`), workspace + member CRUD
- `smadp/tenancy/keys.py` — `signing_keys` table, AES-GCM at-rest encryption, BYOK CRUD
- `smadp/tenancy/deps.py` — FastAPI dependencies: `current_workspace(request)`, `require_role(role)`
- `smadp/transparency/__init__.py`
- `smadp/transparency/journal.py` — `signed_events` table, `append_event`, `verify_chain`, `get_inclusion_proof`
- `smadp/transparency/sigstore.py` — stub `submit_to_rekor(event_id)` and `retry_pending_submissions()` (real Rekor wiring deferred to Plan 2)
- `smadp/transparency/cli.py` — Click subcommands: `verify`, `export`
- `smadp/api/routes/workspaces.py` — `/api/workspaces` router
- `smadp/api/routes/transparency.py` — `/api/transparency` router
- `tests/unit/test_schemas_tenancy.py`
- `tests/unit/test_schemas_transparency.py`
- `tests/unit/test_tenancy_store.py`
- `tests/unit/test_tenancy_keys.py`
- `tests/unit/test_tenancy_deps.py`
- `tests/unit/test_transparency_journal.py`
- `tests/unit/test_transparency_sigstore.py`
- `tests/integration/test_workspaces_api.py`
- `tests/integration/test_transparency_api.py`
- `tests/integration/test_foundation_e2e.py`
- `tests/golden/test_transparency_canonical.py`

**Modify:**
- `pyproject.toml` — add `cryptography>=42.0` to `[project] dependencies`
- `smadp/cli.py` — register the `transparency` Click subgroup
- `smadp/api/routes/__init__.py` — add `workspaces` and `transparency` routers to `ROUTERS`
- `.github/workflows/ci.yml` — add `python -m smadp.cli transparency verify --since=2000-01-01` step

---

## Conventions to follow (from v1)

- All SQLite access uses the `_connect(config)` + `_ensure_schema(conn)` + `_transaction(conn)` pattern from `smadp/sandbox/queue.py:82-107`. Copy that pattern verbatim — do not invent a new one.
- Timestamps stored as ISO-8601 strings ending in `Z` (use `smadp.utils.time.utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")`).
- All Pydantic models use `model_config = ConfigDict(extra="forbid")`.
- All modules use `import structlog` then `log = structlog.get_logger(__name__)`.
- Public functions accept `config: Config | None = None` and call `cfg = config or load_config()`.
- All test fixtures must use `tmp_path` (pytest builtin) for isolation — never write to the real cache dir.
- Tests for env-touching code must use `monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))` at the top of the test.

---

## Task 1: Add `cryptography` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, find the `dependencies = [` block and add `cryptography>=42.0` so it sorts alphabetically:

```toml
dependencies = [
  "anthropic>=0.40.0",
  "click>=8.1",
  "cryptography>=42.0",
  "fastapi>=0.115",
  "httpx>=0.27",
  "jsonschema>=4.22",
  "platformdirs>=4.2",
  "pydantic>=2.7",
  "python-multipart>=0.0.9",
  "pyyaml>=6.0",
  "rich>=13.7",
  "structlog>=24.1",
  "tenacity>=8.5",
  "uvicorn[standard]>=0.30",
  "websockets>=12.0",
]
```

(The existing list is not strictly alphabetical — match the surrounding style if it differs; alphabetical is preferred per ruff `I`.)

- [ ] **Step 2: Install**

Run: `pip install -e ".[dev]"`
Expected: `cryptography` and its transitive deps install successfully.

- [ ] **Step 3: Verify import works**

Run: `python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; print('OK')"`
Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add cryptography for v2-D foundation (Ed25519 + AES-GCM)"
```

---

## Task 2: Tenancy Pydantic schemas

**Files:**
- Create: `smadp/schemas/tenancy.py`
- Create: `tests/unit/test_schemas_tenancy.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_schemas_tenancy.py`:

```python
"""Tests for tenancy Pydantic schemas."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from smadp.schemas.tenancy import Member, Plan, Role, Workspace


def test_workspace_minimal_fields():
    ws = Workspace(
        id="ws_01HXAMPLE",
        name="Acme Corp",
        plan="public",
        created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
    )
    assert ws.id == "ws_01HXAMPLE"
    assert ws.plan == "public"


def test_workspace_rejects_extra_fields():
    with pytest.raises(ValidationError):
        Workspace(
            id="ws_01HXAMPLE",
            name="Acme Corp",
            plan="public",
            created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
            extra_field="boom",
        )


def test_workspace_id_pattern():
    with pytest.raises(ValidationError):
        Workspace(
            id="not-an-id",
            name="Acme",
            plan="public",
            created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        )


def test_plan_enum():
    assert Plan.PUBLIC.value == "public"
    assert Plan.PRIVATE.value == "private"
    with pytest.raises(ValidationError):
        Workspace(
            id="ws_01HXAMPLE",
            name="Acme",
            plan="enterprise",
            created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        )


def test_member_role_enum():
    m = Member(workspace_id="ws_01HXAMPLE", user_id="u_01HABC", role="viewer")
    assert m.role == Role.VIEWER
    with pytest.raises(ValidationError):
        Member(workspace_id="ws_01HXAMPLE", user_id="u_01HABC", role="god")


def test_role_ordering():
    """Ordering encodes privilege escalation; needed by require_role."""
    assert Role.VIEWER < Role.EDITOR < Role.ADMIN < Role.OWNER
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_schemas_tenancy.py -v`
Expected: All tests fail with `ImportError: cannot import name 'Workspace' from 'smadp.schemas.tenancy'`.

- [ ] **Step 3: Implement the schemas**

Create `smadp/schemas/tenancy.py`:

```python
"""Tenancy schemas: workspaces, members, roles, plans (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from functools import total_ordering

from pydantic import BaseModel, ConfigDict, field_validator

WORKSPACE_ID_RE = re.compile(r"^ws_[A-Z0-9]{8,}$")
USER_ID_RE = re.compile(r"^u_[A-Z0-9]{8,}$")


class Plan(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


@total_ordering
class Role(str, Enum):
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"
    OWNER = "owner"

    @property
    def _rank(self) -> int:
        return {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}[self.value]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self._rank < other._rank


class Workspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    plan: Plan
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id_pattern(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    user_id: str
    role: Role

    @field_validator("workspace_id")
    @classmethod
    def _workspace_id(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @field_validator("user_id")
    @classmethod
    def _user_id(cls, v: str) -> str:
        if not USER_ID_RE.match(v):
            raise ValueError(f"Invalid user id: {v!r}")
        return v


__all__ = ["Member", "Plan", "Role", "Workspace"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_schemas_tenancy.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/schemas/tenancy.py tests/unit/test_schemas_tenancy.py
git commit -m "feat(tenancy): add Workspace/Member/Role/Plan schemas"
```

---

## Task 3: Transparency Pydantic schemas

**Files:**
- Create: `smadp/schemas/transparency.py`
- Create: `tests/unit/test_schemas_transparency.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_schemas_transparency.py`:

```python
"""Tests for transparency Pydantic schemas."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from smadp.schemas.transparency import InclusionProof, SignedEvent


def test_signed_event_round_trip():
    ev = SignedEvent(
        id=1,
        event_type="verdict.created",
        payload={"verdict_id": "vdt_01"},
        ts=datetime(2026, 5, 3, tzinfo=timezone.utc),
        prev_hash="sha256:" + "0" * 64,
        signature="aabbccdd",
        rekor_uuid=None,
    )
    assert ev.id == 1
    assert ev.payload["verdict_id"] == "vdt_01"
    dumped = ev.model_dump()
    SignedEvent.model_validate(dumped)


def test_signed_event_extra_forbidden():
    with pytest.raises(ValidationError):
        SignedEvent(
            id=1,
            event_type="x",
            payload={},
            ts=datetime(2026, 5, 3, tzinfo=timezone.utc),
            prev_hash="sha256:" + "0" * 64,
            signature="aa",
            rekor_uuid=None,
            extra="boom",
        )


def test_signed_event_prev_hash_pattern():
    with pytest.raises(ValidationError):
        SignedEvent(
            id=1,
            event_type="x",
            payload={},
            ts=datetime(2026, 5, 3, tzinfo=timezone.utc),
            prev_hash="not-a-hash",
            signature="aa",
            rekor_uuid=None,
        )


def test_inclusion_proof_minimal():
    p = InclusionProof(
        log_id=4827193,
        log_index=4827192,
        leaf_hash="sha256:" + "f" * 64,
        path=["sha256:" + "1" * 64, "sha256:" + "2" * 64],
    )
    assert p.log_index == 4827192
    assert len(p.path) == 2
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/unit/test_schemas_transparency.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the schemas**

Create `smadp/schemas/transparency.py`:

```python
"""Transparency journal schemas (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]+$")


class SignedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    event_type: str
    payload: dict[str, Any]
    ts: datetime
    prev_hash: str
    signature: str
    rekor_uuid: str | None = None

    @field_validator("prev_hash")
    @classmethod
    def _prev_hash(cls, v: str) -> str:
        if not SHA256_RE.match(v):
            raise ValueError(f"Invalid prev_hash: {v!r}")
        return v

    @field_validator("signature")
    @classmethod
    def _signature_hex(cls, v: str) -> str:
        if not HEX_RE.match(v):
            raise ValueError(f"Signature must be lowercase hex, got: {v!r}")
        return v


class InclusionProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_id: int
    log_index: int
    leaf_hash: str
    path: list[str]

    @field_validator("leaf_hash")
    @classmethod
    def _leaf_hash(cls, v: str) -> str:
        if not SHA256_RE.match(v):
            raise ValueError(f"Invalid leaf_hash: {v!r}")
        return v

    @field_validator("path")
    @classmethod
    def _path_hashes(cls, v: list[str]) -> list[str]:
        for h in v:
            if not SHA256_RE.match(h):
                raise ValueError(f"Invalid hash in path: {h!r}")
        return v


__all__ = ["InclusionProof", "SignedEvent"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_schemas_transparency.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/schemas/transparency.py tests/unit/test_schemas_transparency.py
git commit -m "feat(transparency): add SignedEvent and InclusionProof schemas"
```

---

## Task 4: Tenancy store — schema and connection helpers

**Files:**
- Create: `smadp/tenancy/__init__.py`
- Create: `smadp/tenancy/store.py`
- Create: `tests/unit/test_tenancy_store.py` (we will add cases to this file across Tasks 4-6)

- [ ] **Step 1: Write the failing test for connection + schema**

Create `tests/unit/test_tenancy_store.py`:

```python
"""Tests for the tenancy SQLite store."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.tenancy import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    return Config()


def test_schema_creates_tables(cfg: Config):
    conn = store._connect(cfg)
    try:
        store._ensure_schema(conn)
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "workspaces" in names
        assert "workspace_members" in names
    finally:
        conn.close()


def test_db_path_under_cache_dir(cfg: Config):
    p = store._db_path(cfg)
    assert p == cfg.cache_dir / "tenancy.db"
    assert p.parent.exists()
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/unit/test_tenancy_store.py -v`
Expected: `ImportError: cannot import name 'store'`.

- [ ] **Step 3: Create the package + store skeleton**

Create `smadp/tenancy/__init__.py`:

```python
"""Tenancy: workspaces, members, RBAC, BYOK signing keys."""
```

Create `smadp/tenancy/store.py`:

```python
"""SQLite-backed workspace + member store.

Follows the pattern used by ``smadp/sandbox/queue.py``: WAL mode, foreign
keys on, ``BEGIN IMMEDIATE`` for serialized writes, ISO-8601 ``Z`` strings
for timestamps. The DB lives at ``<cache_dir>/tenancy.db``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

import structlog

from smadp.config import Config, load_config

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


__all__: list[str] = []
```

(`__all__` is empty for now; later tasks append to it.)

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_tenancy_store.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/tenancy/__init__.py smadp/tenancy/store.py tests/unit/test_tenancy_store.py
git commit -m "feat(tenancy): SQLite store skeleton (workspaces + members tables)"
```

---

## Task 5: Tenancy store — workspace CRUD

**Files:**
- Modify: `smadp/tenancy/store.py`
- Modify: `tests/unit/test_tenancy_store.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_tenancy_store.py`:

```python
from datetime import datetime

from smadp.schemas.tenancy import Plan, Workspace


def test_create_and_get_workspace(cfg: Config):
    ws = store.create_workspace(name="Acme Corp", plan=Plan.PUBLIC, config=cfg)
    assert ws.id.startswith("ws_")
    assert ws.name == "Acme Corp"
    assert ws.plan == Plan.PUBLIC
    fetched = store.get_workspace(ws.id, config=cfg)
    assert fetched == ws


def test_get_missing_workspace_raises(cfg: Config):
    with pytest.raises(KeyError):
        store.get_workspace("ws_DOESNOTEXIST", config=cfg)


def test_list_workspaces_returns_in_creation_order(cfg: Config):
    a = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    b = store.create_workspace(name="B", plan=Plan.PRIVATE, config=cfg)
    listed = store.list_workspaces(config=cfg)
    assert [w.id for w in listed] == [a.id, b.id]


def test_delete_workspace_cascades(cfg: Config):
    ws = store.create_workspace(name="X", plan=Plan.PUBLIC, config=cfg)
    store.delete_workspace(ws.id, config=cfg)
    with pytest.raises(KeyError):
        store.get_workspace(ws.id, config=cfg)


def test_workspace_id_format(cfg: Config):
    """Workspace IDs must match ws_<8+ uppercase alnum>."""
    import re
    ws = store.create_workspace(name="Y", plan=Plan.PRIVATE, config=cfg)
    assert re.match(r"^ws_[A-Z0-9]{8,}$", ws.id)
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/unit/test_tenancy_store.py -v`
Expected: 5 failures with `AttributeError: module 'smadp.tenancy.store' has no attribute 'create_workspace'`.

- [ ] **Step 3: Implement workspace CRUD**

Append to `smadp/tenancy/store.py` (add the imports near the top first):

```python
# Add to top imports:
import secrets
import sqlite3  # already imported

from smadp.schemas.tenancy import Plan, Workspace
from smadp.utils.time import utcnow
```

Then append the functions to the bottom of the file (above `__all__`):

```python
def _generate_workspace_id() -> str:
    """Sortable, case-insensitive base32-ish id: ws_<8 uppercase alphanum>."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "ws_" + "".join(secrets.choice(alphabet) for _ in range(8))


def _row_to_workspace(row: sqlite3.Row) -> Workspace:
    from datetime import datetime
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
        cur = conn.execute("SELECT * FROM workspaces ORDER BY created_at ASC, id ASC")
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
```

Update `__all__` at the bottom of `store.py`:

```python
__all__ = [
    "create_workspace",
    "delete_workspace",
    "get_workspace",
    "list_workspaces",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_tenancy_store.py -v`
Expected: 7 passed (2 from Task 4 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add smadp/tenancy/store.py tests/unit/test_tenancy_store.py
git commit -m "feat(tenancy): workspace CRUD"
```

---

## Task 6: Tenancy store — member CRUD + role lookup

**Files:**
- Modify: `smadp/tenancy/store.py`
- Modify: `tests/unit/test_tenancy_store.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_tenancy_store.py`:

```python
from smadp.schemas.tenancy import Member, Role


def test_add_and_get_member(cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    m = store.add_member(
        workspace_id=ws.id, user_id="u_USER0001", role=Role.EDITOR, config=cfg
    )
    assert m.role == Role.EDITOR
    fetched = store.get_member_role(workspace_id=ws.id, user_id="u_USER0001", config=cfg)
    assert fetched == Role.EDITOR


def test_get_missing_member_returns_none(cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    role = store.get_member_role(workspace_id=ws.id, user_id="u_NOPE0001", config=cfg)
    assert role is None


def test_add_member_idempotent_upserts_role(cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    store.add_member(workspace_id=ws.id, user_id="u_USER0001", role=Role.VIEWER, config=cfg)
    store.add_member(workspace_id=ws.id, user_id="u_USER0001", role=Role.ADMIN, config=cfg)
    assert (
        store.get_member_role(workspace_id=ws.id, user_id="u_USER0001", config=cfg)
        == Role.ADMIN
    )


def test_remove_member(cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    store.add_member(workspace_id=ws.id, user_id="u_USER0001", role=Role.OWNER, config=cfg)
    store.remove_member(workspace_id=ws.id, user_id="u_USER0001", config=cfg)
    assert (
        store.get_member_role(workspace_id=ws.id, user_id="u_USER0001", config=cfg) is None
    )


def test_list_members(cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    store.add_member(workspace_id=ws.id, user_id="u_USER0001", role=Role.OWNER, config=cfg)
    store.add_member(workspace_id=ws.id, user_id="u_USER0002", role=Role.VIEWER, config=cfg)
    listed = store.list_members(workspace_id=ws.id, config=cfg)
    assert {m.user_id for m in listed} == {"u_USER0001", "u_USER0002"}


def test_member_cascade_on_workspace_delete(cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    store.add_member(workspace_id=ws.id, user_id="u_USER0001", role=Role.OWNER, config=cfg)
    store.delete_workspace(ws.id, config=cfg)
    # Workspace gone; member rows should be gone too thanks to ON DELETE CASCADE.
    conn = store._connect(cfg)
    try:
        store._ensure_schema(conn)
        cur = conn.execute(
            "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = ?", (ws.id,)
        )
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/unit/test_tenancy_store.py -v`
Expected: 6 failures with `AttributeError`.

- [ ] **Step 3: Implement member CRUD**

Append to `smadp/tenancy/store.py`:

```python
from smadp.schemas.tenancy import Member, Role  # add to imports if missing


def _row_to_member(row: sqlite3.Row) -> Member:
    return Member(
        workspace_id=row["workspace_id"],
        user_id=row["user_id"],
        role=Role(row["role"]),
    )


def add_member(
    *,
    workspace_id: str,
    user_id: str,
    role: Role,
    config: Config | None = None,
) -> Member:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO workspace_members(workspace_id, user_id, role) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(workspace_id, user_id) DO UPDATE SET role = excluded.role",
                (workspace_id, user_id, role.value),
            )
        log.info(
            "tenancy.member.upserted",
            workspace_id=workspace_id,
            user_id=user_id,
            role=role.value,
        )
        return Member(workspace_id=workspace_id, user_id=user_id, role=role)
    finally:
        conn.close()


def get_member_role(
    *,
    workspace_id: str,
    user_id: str,
    config: Config | None = None,
) -> Role | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        )
        row = cur.fetchone()
        return Role(row["role"]) if row else None
    finally:
        conn.close()


def remove_member(
    *,
    workspace_id: str,
    user_id: str,
    config: Config | None = None,
) -> None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        with _transaction(conn):
            conn.execute(
                "DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                (workspace_id, user_id),
            )
        log.info("tenancy.member.removed", workspace_id=workspace_id, user_id=user_id)
    finally:
        conn.close()


def list_members(
    *,
    workspace_id: str,
    config: Config | None = None,
) -> list[Member]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM workspace_members WHERE workspace_id = ? "
            "ORDER BY user_id ASC",
            (workspace_id,),
        )
        return [_row_to_member(r) for r in cur.fetchall()]
    finally:
        conn.close()
```

Update `__all__`:

```python
__all__ = [
    "add_member",
    "create_workspace",
    "delete_workspace",
    "get_member_role",
    "get_workspace",
    "list_members",
    "list_workspaces",
    "remove_member",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_tenancy_store.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/tenancy/store.py tests/unit/test_tenancy_store.py
git commit -m "feat(tenancy): member CRUD with role upsert + cascade delete"
```

---

## Task 7: Tenancy keys — AES-GCM + signing key store

**Files:**
- Create: `smadp/tenancy/keys.py`
- Create: `tests/unit/test_tenancy_keys.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_tenancy_keys.py`:

```python
"""Tests for BYOK signing-key storage with AES-GCM at-rest encryption."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)  # 32 hex bytes for tests
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    return store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg).id


def test_upload_and_load_byok_key(cfg: Config, workspace_id: str):
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(
        workspace_id=workspace_id, private_key=priv, config=cfg
    )
    loaded = keys.load_signing_key(workspace_id=workspace_id, config=cfg)
    assert loaded is not None
    # Signing the same message with both keys should produce the same signature.
    msg = b"hello transparency"
    assert priv.sign(msg) == loaded.sign(msg)


def test_load_missing_key_returns_none(cfg: Config, workspace_id: str):
    assert keys.load_signing_key(workspace_id=workspace_id, config=cfg) is None


def test_aes_gcm_round_trip_with_kek(cfg: Config, workspace_id: str):
    plaintext = b"secret payload"
    nonce, ciphertext = keys._encrypt(plaintext, workspace_id=workspace_id, config=cfg)
    assert ciphertext != plaintext
    recovered = keys._decrypt(
        nonce=nonce, ciphertext=ciphertext, workspace_id=workspace_id, config=cfg
    )
    assert recovered == plaintext


def test_corrupted_ciphertext_fails(cfg: Config, workspace_id: str):
    plaintext = b"x"
    nonce, ciphertext = keys._encrypt(plaintext, workspace_id=workspace_id, config=cfg)
    bad = bytes([ciphertext[0] ^ 0xFF]) + ciphertext[1:]
    with pytest.raises(Exception):  # InvalidTag from cryptography
        keys._decrypt(
            nonce=nonce, ciphertext=bad, workspace_id=workspace_id, config=cfg
        )


def test_kek_master_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("SMADP_KEK_MASTER", raising=False)
    cfg = Config()
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    priv = Ed25519PrivateKey.generate()
    with pytest.raises(RuntimeError, match="SMADP_KEK_MASTER"):
        keys.upload_signing_key(workspace_id=ws.id, private_key=priv, config=cfg)


def test_rotate_key_preserves_old_pub(cfg: Config, workspace_id: str):
    old = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=workspace_id, private_key=old, config=cfg)
    new = Ed25519PrivateKey.generate()
    keys.rotate_signing_key(workspace_id=workspace_id, new_private_key=new, config=cfg)
    loaded = keys.load_signing_key(workspace_id=workspace_id, config=cfg)
    assert loaded is not None
    assert loaded.sign(b"x") == new.sign(b"x")
    # rotated_from is preserved for verification of historical passports.
    rotated_from = keys.get_rotated_from(workspace_id=workspace_id, config=cfg)
    assert rotated_from is not None
```

- [ ] **Step 2: Run — expect ImportError**

Run: `pytest tests/unit/test_tenancy_keys.py -v`
Expected: ImportError on `smadp.tenancy.keys`.

- [ ] **Step 3: Implement `smadp/tenancy/keys.py`**

Create `smadp/tenancy/keys.py`:

```python
"""BYOK signing-key storage with AES-GCM at-rest encryption.

The DEK is the per-workspace AES-GCM key, derived from the deployment-wide
master KEK (env var ``SMADP_KEK_MASTER``, 64 hex chars = 32 bytes) plus the
workspace id as salt via HKDF-SHA256. This means:

* Compromise of any single workspace's ciphertext leaks nothing about others.
* The master KEK is the only secret the operator must hold outside SQLite.
* Re-keying the master KEK is an offline migration (out of scope for v2-D
  Plan 1; tracked for Plan 7+).

For unit tests, set ``SMADP_KEK_MASTER`` to ``"0" * 64`` via monkeypatch.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path
from typing import Final

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from smadp.config import Config, load_config
from smadp.tenancy.store import _connect, _ensure_schema, _transaction
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)

KEK_ENV: Final[str] = "SMADP_KEK_MASTER"

_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS signing_keys (
    workspace_id TEXT PRIMARY KEY,
    algorithm TEXT NOT NULL CHECK(algorithm = 'ed25519'),
    public_key BLOB NOT NULL,
    nonce BLOB NOT NULL,
    private_key_encrypted BLOB NOT NULL,
    created_at TEXT NOT NULL,
    rotated_from TEXT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
"""


def _ensure_keys_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


def _master_kek() -> bytes:
    raw = os.environ.get(KEK_ENV)
    if not raw:
        raise RuntimeError(
            f"{KEK_ENV} is not set; cannot encrypt/decrypt BYOK signing keys."
        )
    if len(raw) != 64:
        raise RuntimeError(
            f"{KEK_ENV} must be 64 hex chars (32 bytes), got {len(raw)} chars."
        )
    try:
        return bytes.fromhex(raw)
    except ValueError as e:
        raise RuntimeError(f"{KEK_ENV} is not valid hex: {e}") from e


def _derive_dek(workspace_id: str) -> bytes:
    """HKDF(master KEK, salt=workspace_id) -> 32-byte AES-GCM key."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=workspace_id.encode("utf-8"),
        info=b"smadp/byok/v1",
    ).derive(_master_kek())


def _encrypt(
    plaintext: bytes, *, workspace_id: str, config: Config | None = None
) -> tuple[bytes, bytes]:
    dek = _derive_dek(workspace_id)
    aes = AESGCM(dek)
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext, associated_data=workspace_id.encode("utf-8"))
    return nonce, ct


def _decrypt(
    *, nonce: bytes, ciphertext: bytes, workspace_id: str, config: Config | None = None
) -> bytes:
    dek = _derive_dek(workspace_id)
    aes = AESGCM(dek)
    return aes.decrypt(nonce, ciphertext, associated_data=workspace_id.encode("utf-8"))


def upload_signing_key(
    *,
    workspace_id: str,
    private_key: Ed25519PrivateKey,
    config: Config | None = None,
) -> None:
    cfg = config or load_config()
    priv_bytes = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    pub_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    nonce, encrypted = _encrypt(priv_bytes, workspace_id=workspace_id, config=cfg)
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO signing_keys"
                "(workspace_id, algorithm, public_key, nonce, "
                " private_key_encrypted, created_at, rotated_from) "
                "VALUES (?, 'ed25519', ?, ?, ?, ?, NULL)",
                (workspace_id, pub_bytes, nonce, encrypted, now_iso),
            )
        log.info("tenancy.byok.uploaded", workspace_id=workspace_id)
    finally:
        conn.close()


def load_signing_key(
    *, workspace_id: str, config: Config | None = None
) -> Ed25519PrivateKey | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        cur = conn.execute(
            "SELECT nonce, private_key_encrypted FROM signing_keys "
            "WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        priv_bytes = _decrypt(
            nonce=row["nonce"],
            ciphertext=row["private_key_encrypted"],
            workspace_id=workspace_id,
            config=cfg,
        )
        return Ed25519PrivateKey.from_private_bytes(priv_bytes)
    finally:
        conn.close()


def rotate_signing_key(
    *,
    workspace_id: str,
    new_private_key: Ed25519PrivateKey,
    config: Config | None = None,
) -> None:
    """Replace the workspace's signing key, retaining the old public key id."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        cur = conn.execute(
            "SELECT public_key FROM signing_keys WHERE workspace_id = ?",
            (workspace_id,),
        )
        existing = cur.fetchone()
        old_pub_hex = existing["public_key"].hex() if existing else None
        priv_bytes = new_private_key.private_bytes(
            encoding=Encoding.Raw,
            format=PrivateFormat.Raw,
            encryption_algorithm=NoEncryption(),
        )
        pub_bytes = new_private_key.public_key().public_bytes(
            encoding=Encoding.Raw, format=PublicFormat.Raw
        )
        nonce, encrypted = _encrypt(priv_bytes, workspace_id=workspace_id, config=cfg)
        now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
        with _transaction(conn):
            conn.execute(
                "INSERT INTO signing_keys"
                "(workspace_id, algorithm, public_key, nonce, "
                " private_key_encrypted, created_at, rotated_from) "
                "VALUES (?, 'ed25519', ?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace_id) DO UPDATE SET "
                " public_key = excluded.public_key,"
                " nonce = excluded.nonce,"
                " private_key_encrypted = excluded.private_key_encrypted,"
                " created_at = excluded.created_at,"
                " rotated_from = excluded.rotated_from",
                (workspace_id, pub_bytes, nonce, encrypted, now_iso, old_pub_hex),
            )
        log.info("tenancy.byok.rotated", workspace_id=workspace_id)
    finally:
        conn.close()


def get_rotated_from(
    *, workspace_id: str, config: Config | None = None
) -> str | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        cur = conn.execute(
            "SELECT rotated_from FROM signing_keys WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        return row["rotated_from"] if row else None
    finally:
        conn.close()


def get_public_key(
    *, workspace_id: str, config: Config | None = None
) -> Ed25519PublicKey | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        cur = conn.execute(
            "SELECT public_key FROM signing_keys WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return Ed25519PublicKey.from_public_bytes(row["public_key"])
    finally:
        conn.close()


__all__ = [
    "KEK_ENV",
    "get_public_key",
    "get_rotated_from",
    "load_signing_key",
    "rotate_signing_key",
    "upload_signing_key",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_tenancy_keys.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/tenancy/keys.py tests/unit/test_tenancy_keys.py
git commit -m "feat(tenancy): BYOK signing-key store with AES-GCM at-rest encryption"
```

---

## Task 8: FastAPI deps — `current_workspace` and `require_role`

**Files:**
- Create: `smadp/tenancy/deps.py`
- Create: `tests/unit/test_tenancy_deps.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_tenancy_deps.py`:

```python
"""Tests for FastAPI tenancy dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from smadp.config import Config
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import deps, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    return Config()


@pytest.fixture
def app(cfg: Config) -> FastAPI:
    a = FastAPI()
    a.state.config = cfg

    @a.get("/probe")
    def probe(ws=Depends(deps.current_workspace)):
        return {"workspace_id": ws.id}

    @a.get("/admin-only")
    def admin(_=Depends(deps.require_role(Role.ADMIN))):
        return {"ok": True}

    return a


def test_current_workspace_resolves_from_header(app, cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    store.add_member(
        workspace_id=ws.id, user_id="u_USER0001", role=Role.VIEWER, config=cfg
    )
    client = TestClient(app)
    r = client.get(
        "/probe",
        headers={"X-SMADP-Workspace": ws.id, "X-SMADP-User": "u_USER0001"},
    )
    assert r.status_code == 200
    assert r.json() == {"workspace_id": ws.id}


def test_missing_workspace_header_403(app, cfg: Config):
    client = TestClient(app)
    r = client.get("/probe")
    assert r.status_code == 403


def test_unknown_workspace_404(app, cfg: Config):
    client = TestClient(app)
    r = client.get(
        "/probe",
        headers={"X-SMADP-Workspace": "ws_DOESNOTEXIST", "X-SMADP-User": "u_USER0001"},
    )
    assert r.status_code == 404


def test_require_role_passes_when_role_meets_threshold(app, cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PRIVATE, config=cfg)
    store.add_member(
        workspace_id=ws.id, user_id="u_USER0001", role=Role.OWNER, config=cfg
    )
    client = TestClient(app)
    r = client.get(
        "/admin-only",
        headers={"X-SMADP-Workspace": ws.id, "X-SMADP-User": "u_USER0001"},
    )
    assert r.status_code == 200


def test_require_role_blocks_lower_role(app, cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PRIVATE, config=cfg)
    store.add_member(
        workspace_id=ws.id, user_id="u_USER0001", role=Role.EDITOR, config=cfg
    )
    client = TestClient(app)
    r = client.get(
        "/admin-only",
        headers={"X-SMADP-Workspace": ws.id, "X-SMADP-User": "u_USER0001"},
    )
    assert r.status_code == 403


def test_require_role_blocks_non_member(app, cfg: Config):
    ws = store.create_workspace(name="A", plan=Plan.PRIVATE, config=cfg)
    client = TestClient(app)
    r = client.get(
        "/admin-only",
        headers={"X-SMADP-Workspace": ws.id, "X-SMADP-User": "u_NONMEMB"},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run — expect ImportError**

Run: `pytest tests/unit/test_tenancy_deps.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `smadp/tenancy/deps.py`**

Create `smadp/tenancy/deps.py`:

```python
"""FastAPI dependencies for tenancy + RBAC.

Headers:

* ``X-SMADP-Workspace`` — workspace id the request operates against
* ``X-SMADP-User`` — caller's user id (resolved by upstream auth, e.g. an
  API gateway or session middleware; v2-D Plan 1 does not implement auth
  itself — that ships in Plan 7 alongside billing)

In v2-D Plan 1 these are simply read from headers without verification;
the auth surface attaches in a later plan. Until then, treat any callsite
that uses these dependencies as ``protected by upstream auth``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request

from smadp.config import Config
from smadp.schemas.tenancy import Role, Workspace
from smadp.tenancy import store


def _config_from_request(request: Request) -> Config:
    cfg = getattr(request.app.state, "config", None)
    if cfg is None:
        raise HTTPException(
            status_code=500,
            detail="App state missing 'config' — wire it via app.state.config = Config().",
        )
    return cfg


def current_workspace(request: Request) -> Workspace:
    """Resolve the workspace from ``X-SMADP-Workspace`` or 403/404."""
    ws_id = request.headers.get("X-SMADP-Workspace")
    if not ws_id:
        raise HTTPException(status_code=403, detail="X-SMADP-Workspace header required")
    cfg = _config_from_request(request)
    try:
        return store.get_workspace(ws_id, config=cfg)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def current_user_id(request: Request) -> str:
    user_id = request.headers.get("X-SMADP-User")
    if not user_id:
        raise HTTPException(status_code=403, detail="X-SMADP-User header required")
    return user_id


def require_role(min_role: Role) -> Callable[..., Any]:
    """Return a dependency that asserts the caller has ``>= min_role`` in workspace."""

    def _check(
        request: Request,
        ws: Workspace = Depends(current_workspace),
        user_id: str = Depends(current_user_id),
    ) -> Workspace:
        cfg = _config_from_request(request)
        actual = store.get_member_role(workspace_id=ws.id, user_id=user_id, config=cfg)
        if actual is None:
            raise HTTPException(
                status_code=403,
                detail=f"User {user_id!r} is not a member of {ws.id!r}",
            )
        if actual < min_role:
            raise HTTPException(
                status_code=403,
                detail=f"Need {min_role.value} or higher; have {actual.value}",
            )
        return ws

    return _check


__all__ = ["current_user_id", "current_workspace", "require_role"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_tenancy_deps.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/tenancy/deps.py tests/unit/test_tenancy_deps.py
git commit -m "feat(tenancy): FastAPI deps current_workspace + require_role"
```

---

## Task 9: Transparency journal — schema, append, signature

**Files:**
- Create: `smadp/transparency/__init__.py`
- Create: `smadp/transparency/journal.py`
- Create: `tests/unit/test_transparency_journal.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_transparency_journal.py`:

```python
"""Tests for the transparency log (signed-event journal)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.transparency import journal


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    return Config()


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def test_append_event_returns_event_with_id(cfg: Config, signing_key):
    ev = journal.append_event(
        event_type="verdict.created",
        payload={"verdict_id": "vdt_x"},
        signing_key=signing_key,
        config=cfg,
    )
    assert ev.id == 1
    assert ev.event_type == "verdict.created"
    assert ev.signature  # hex-encoded


def test_append_event_chain_links_prev_hash(cfg: Config, signing_key):
    a = journal.append_event(
        event_type="x.a", payload={}, signing_key=signing_key, config=cfg
    )
    b = journal.append_event(
        event_type="x.b", payload={}, signing_key=signing_key, config=cfg
    )
    assert a.prev_hash == "sha256:" + "0" * 64  # genesis
    # b.prev_hash should be sha256 of a.signature
    expected = journal._hash_signature(a.signature)
    assert b.prev_hash == expected


def test_append_event_signature_verifies(cfg: Config, signing_key):
    ev = journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=signing_key, config=cfg
    )
    pub = signing_key.public_key()
    pub.verify(
        bytes.fromhex(ev.signature),
        journal._canonical_signing_input(ev),
    )  # raises on bad signature


def test_payload_canonicalization_is_stable(cfg: Config, signing_key):
    ev_a = journal.append_event(
        event_type="x", payload={"a": 1, "b": 2}, signing_key=signing_key, config=cfg
    )
    ev_b = journal.append_event(
        event_type="x", payload={"b": 2, "a": 1}, signing_key=signing_key, config=cfg
    )
    sig_input_a = journal._canonical_signing_input(ev_a)
    sig_input_b = journal._canonical_signing_input(ev_b)
    # Same payload (different key order in source) → same canonical bytes
    # except for id, ts, prev_hash. Strip those for comparison.
    # Easier: just verify both canonicalize their dict identically.
    assert journal._canonical_payload({"a": 1, "b": 2}) == journal._canonical_payload(
        {"b": 2, "a": 1}
    )
```

- [ ] **Step 2: Run — expect ImportError**

Run: `pytest tests/unit/test_transparency_journal.py -v`
Expected: ImportError.

- [ ] **Step 3: Create the package + implement append + signing**

Create `smadp/transparency/__init__.py`:

```python
"""Transparency log: append-only signed-event journal."""
```

Create `smadp/transparency/journal.py`:

```python
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
                signature="00",  # not yet — placeholder for schema validation
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_transparency_journal.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/transparency/__init__.py smadp/transparency/journal.py tests/unit/test_transparency_journal.py
git commit -m "feat(transparency): append_event with Ed25519 signature + chain linking"
```

---

## Task 10: Transparency journal — `verify_chain` + tamper detection

**Files:**
- Modify: `smadp/transparency/journal.py`
- Modify: `tests/unit/test_transparency_journal.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_transparency_journal.py`:

```python
def test_verify_chain_passes_on_clean_log(cfg: Config, signing_key):
    journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=signing_key, config=cfg
    )
    journal.append_event(
        event_type="x.b", payload={"k": 2}, signing_key=signing_key, config=cfg
    )
    journal.append_event(
        event_type="x.c", payload={"k": 3}, signing_key=signing_key, config=cfg
    )
    result = journal.verify_chain(
        public_key=signing_key.public_key(), config=cfg
    )
    assert result.valid is True
    assert result.first_break is None


def test_verify_chain_detects_payload_tamper(cfg: Config, signing_key):
    journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=signing_key, config=cfg
    )
    journal.append_event(
        event_type="x.b", payload={"k": 2}, signing_key=signing_key, config=cfg
    )
    # Corrupt row 1's payload directly.
    conn = journal._connect(cfg)
    try:
        conn.execute("UPDATE signed_events SET payload = ? WHERE id = 1", ('{"k":99}',))
    finally:
        conn.close()
    result = journal.verify_chain(public_key=signing_key.public_key(), config=cfg)
    assert result.valid is False
    assert result.first_break == 1
    assert "signature" in result.reason.lower()


def test_verify_chain_detects_prev_hash_break(cfg: Config, signing_key):
    journal.append_event(
        event_type="x.a", payload={}, signing_key=signing_key, config=cfg
    )
    journal.append_event(
        event_type="x.b", payload={}, signing_key=signing_key, config=cfg
    )
    conn = journal._connect(cfg)
    try:
        conn.execute(
            "UPDATE signed_events SET prev_hash = ? WHERE id = 2",
            ("sha256:" + "f" * 64,),
        )
    finally:
        conn.close()
    result = journal.verify_chain(public_key=signing_key.public_key(), config=cfg)
    assert result.valid is False
    assert result.first_break == 2
    assert "prev_hash" in result.reason.lower()


def test_verify_chain_handles_empty_log(cfg: Config, signing_key):
    result = journal.verify_chain(public_key=signing_key.public_key(), config=cfg)
    assert result.valid is True


def test_iter_events(cfg: Config, signing_key):
    journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=signing_key, config=cfg
    )
    journal.append_event(
        event_type="x.b", payload={"k": 2}, signing_key=signing_key, config=cfg
    )
    rows = list(journal.iter_events(config=cfg))
    assert len(rows) == 2
    assert [r.event_type for r in rows] == ["x.a", "x.b"]
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/unit/test_transparency_journal.py -v`
Expected: 5 failures with `AttributeError: ... has no attribute 'verify_chain'`.

- [ ] **Step 3: Implement `verify_chain` and `iter_events`**

Append to `smadp/transparency/journal.py` (above `__all__`):

```python
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass(frozen=True)
class VerificationReport:
    valid: bool
    first_break: int | None
    reason: str


def iter_events(*, config: Config | None = None) -> Iterator[SignedEvent]:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute("SELECT * FROM signed_events ORDER BY id ASC")
        for row in cur.fetchall():
            yield SignedEvent(
                id=row["id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload"]),
                ts=datetime.fromisoformat(row["ts"].replace("Z", "+00:00")),
                prev_hash=row["prev_hash"],
                signature=row["signature"],
                rekor_uuid=row["rekor_uuid"],
            )
    finally:
        conn.close()


def verify_chain(
    *,
    public_key: Ed25519PublicKey,
    config: Config | None = None,
) -> VerificationReport:
    """Walk the journal and verify every signature + chain link.

    Returns the first break encountered, or ``valid=True`` if intact.
    """
    cfg = config or load_config()
    expected_prev = GENESIS_PREV_HASH
    for ev in iter_events(config=cfg):
        # 1. chain link
        if ev.prev_hash != expected_prev:
            return VerificationReport(
                valid=False,
                first_break=ev.id,
                reason=f"prev_hash mismatch at id {ev.id}: expected {expected_prev}",
            )
        # 2. signature
        try:
            public_key.verify(
                bytes.fromhex(ev.signature), _canonical_signing_input(ev)
            )
        except (InvalidSignature, ValueError) as e:
            return VerificationReport(
                valid=False,
                first_break=ev.id,
                reason=f"signature invalid at id {ev.id}: {type(e).__name__}",
            )
        expected_prev = _hash_signature(ev.signature)
    return VerificationReport(valid=True, first_break=None, reason="ok")
```

Update `__all__`:

```python
__all__ = [
    "GENESIS_PREV_HASH",
    "VerificationReport",
    "append_event",
    "iter_events",
    "verify_chain",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_transparency_journal.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/transparency/journal.py tests/unit/test_transparency_journal.py
git commit -m "feat(transparency): verify_chain + iter_events with tamper detection"
```

---

## Task 11: Golden test — canonical signing input is byte-stable

**Files:**
- Create: `tests/golden/test_transparency_canonical.py`

- [ ] **Step 1: Write the golden test**

Create `tests/golden/test_transparency_canonical.py`:

```python
"""Golden test: the canonical signing input for SignedEvents is byte-stable.

Any change to ``_canonical_signing_input`` would invalidate every
existing transparency log. The expected bytes here are the contract.
"""

from __future__ import annotations

from datetime import datetime, timezone

from smadp.schemas.transparency import SignedEvent
from smadp.transparency.journal import _canonical_payload, _canonical_signing_input


def test_canonical_payload_byte_stable():
    a = _canonical_payload({"alpha": 1, "beta": [2, 3], "gamma": {"x": "y"}})
    b = _canonical_payload({"gamma": {"x": "y"}, "beta": [2, 3], "alpha": 1})
    assert a == b
    assert a == b'{"alpha":1,"beta":[2,3],"gamma":{"x":"y"}}'


def test_canonical_signing_input_byte_stable():
    ev = SignedEvent(
        id=42,
        event_type="verdict.created",
        payload={"verdict_id": "vdt_x", "score": 0.31},
        ts=datetime(2026, 5, 3, 12, 34, 56, 789000, tzinfo=timezone.utc),
        prev_hash="sha256:" + "0" * 64,
        signature="aabbccdd",
    )
    out = _canonical_signing_input(ev)
    assert out == (
        b'{"event_type":"verdict.created","id":42,'
        b'"payload":{"score":0.31,"verdict_id":"vdt_x"},'
        b'"prev_hash":"sha256:0000000000000000000000000000000000000000'
        b'00000000000000000000000000",'
        b'"ts":"2026-05-03T12:34:56.789Z"}'
    )


def test_canonical_signing_input_omits_signature_and_rekor():
    """The signing input is what gets signed — it must not include the
    signature itself or the rekor_uuid (which is set after signing)."""
    ev = SignedEvent(
        id=1,
        event_type="x",
        payload={},
        ts=datetime(2026, 5, 3, tzinfo=timezone.utc),
        prev_hash="sha256:" + "0" * 64,
        signature="aa",
        rekor_uuid="should-not-appear",
    )
    out = _canonical_signing_input(ev)
    assert b"signature" not in out
    assert b"rekor" not in out
    assert b"should-not-appear" not in out
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/golden/test_transparency_canonical.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/golden/test_transparency_canonical.py
git commit -m "test(transparency): golden test for canonical signing input"
```

---

## Task 12: Sigstore stub — deferred submission table + retry hook

**Files:**
- Create: `smadp/transparency/sigstore.py`
- Create: `tests/unit/test_transparency_sigstore.py`

> **Note for engineer:** Real Rekor wiring is deferred to Plan 2 (Passport). This task creates the stub surface — `submit_to_rekor` returns `None` (deferred) and `retry_pending_submissions` walks the not-yet-submitted rows. The point is to lock down the API shape and the queue semantics so Plan 2 only has to fill in the HTTP call.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_transparency_sigstore.py`:

```python
"""Tests for sigstore deferred-submission stub."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.transparency import journal, sigstore


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    return Config()


@pytest.fixture
def key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def test_submit_to_rekor_stub_returns_none(cfg: Config, key):
    ev = journal.append_event(
        event_type="x", payload={}, signing_key=key, config=cfg
    )
    result = sigstore.submit_to_rekor(event_id=ev.id, config=cfg)
    assert result is None  # stub: real submission deferred


def test_pending_submissions_lists_unsubmitted(cfg: Config, key):
    ev1 = journal.append_event(event_type="x", payload={}, signing_key=key, config=cfg)
    ev2 = journal.append_event(event_type="y", payload={}, signing_key=key, config=cfg)
    pending = sigstore.list_pending_submissions(config=cfg)
    assert {p.id for p in pending} == {ev1.id, ev2.id}


def test_mark_submitted_clears_pending(cfg: Config, key):
    ev = journal.append_event(event_type="x", payload={}, signing_key=key, config=cfg)
    sigstore.mark_submitted(event_id=ev.id, rekor_uuid="rkr_test_uuid", config=cfg)
    pending = sigstore.list_pending_submissions(config=cfg)
    assert all(p.id != ev.id for p in pending)


def test_retry_pending_calls_submit_per_row(cfg: Config, key, monkeypatch):
    journal.append_event(event_type="x", payload={}, signing_key=key, config=cfg)
    journal.append_event(event_type="y", payload={}, signing_key=key, config=cfg)

    calls: list[int] = []

    def fake_submit(*, event_id: int, config=None) -> str | None:
        calls.append(event_id)
        return f"rkr_{event_id}"

    monkeypatch.setattr(sigstore, "submit_to_rekor", fake_submit)
    sigstore.retry_pending_submissions(config=cfg)
    assert sorted(calls) == [1, 2]
    assert sigstore.list_pending_submissions(config=cfg) == []
```

- [ ] **Step 2: Run — expect ImportError**

Run: `pytest tests/unit/test_transparency_sigstore.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `smadp/transparency/sigstore.py`**

Create `smadp/transparency/sigstore.py`:

```python
"""Sigstore (Rekor) submission stubs — real wiring lands in Plan 2.

Plan 1 establishes:

* the ``signed_events.rekor_uuid`` column (already in ``journal.py`` schema)
* a queue API so retries are uniform
* a stub ``submit_to_rekor`` that returns ``None`` (deferred)

Plan 2 swaps the stub for a real ``sigstore`` client call. The interface
shape — ``submit_to_rekor(event_id) -> rekor_uuid | None`` and
``retry_pending_submissions()`` — is the contract Plan 2 must honor.
"""

from __future__ import annotations

import structlog

from smadp.config import Config, load_config
from smadp.schemas.transparency import SignedEvent
from smadp.transparency.journal import _connect, _ensure_schema, iter_events

log = structlog.get_logger(__name__)


def submit_to_rekor(*, event_id: int, config: Config | None = None) -> str | None:
    """STUB: returns None to indicate deferred submission.

    Plan 2 replaces this with a real Sigstore client call that returns
    the assigned Rekor UUID.
    """
    log.info("transparency.sigstore.deferred", event_id=event_id)
    return None


def list_pending_submissions(*, config: Config | None = None) -> list[SignedEvent]:
    cfg = config or load_config()
    return [ev for ev in iter_events(config=cfg) if ev.rekor_uuid is None]


def mark_submitted(
    *, event_id: int, rekor_uuid: str, config: Config | None = None
) -> None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "UPDATE signed_events SET rekor_uuid = ? WHERE id = ? AND rekor_uuid IS NULL",
            (rekor_uuid, event_id),
        )
        if cur.rowcount == 0:
            raise KeyError(
                f"No pending event with id {event_id!r}; already submitted or absent."
            )
        log.info(
            "transparency.sigstore.submitted",
            event_id=event_id,
            rekor_uuid=rekor_uuid,
        )
    finally:
        conn.close()


def retry_pending_submissions(*, config: Config | None = None) -> int:
    """Iterate pending events, call ``submit_to_rekor``, mark submitted on success.

    Returns the number of events successfully submitted.
    """
    cfg = config or load_config()
    submitted = 0
    for ev in list_pending_submissions(config=cfg):
        rekor_uuid = submit_to_rekor(event_id=ev.id, config=cfg)
        if rekor_uuid is not None:
            mark_submitted(event_id=ev.id, rekor_uuid=rekor_uuid, config=cfg)
            submitted += 1
    return submitted


__all__ = [
    "list_pending_submissions",
    "mark_submitted",
    "retry_pending_submissions",
    "submit_to_rekor",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_transparency_sigstore.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/transparency/sigstore.py tests/unit/test_transparency_sigstore.py
git commit -m "feat(transparency): sigstore submission stub + retry queue"
```

---

## Task 13: Workspaces API router

**Files:**
- Create: `smadp/api/routes/workspaces.py`
- Create: `tests/integration/test_workspaces_api.py`
- Modify: `smadp/api/routes/__init__.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_workspaces_api.py`:

```python
"""Integration tests for /api/workspaces."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return TestClient(create_app(Config()))


def test_create_workspace(client: TestClient):
    r = client.post(
        "/api/workspaces",
        json={"name": "Acme Corp", "plan": "private"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Acme Corp"
    assert body["plan"] == "private"
    assert body["id"].startswith("ws_")


def test_get_workspace(client: TestClient):
    created = client.post(
        "/api/workspaces", json={"name": "X", "plan": "public"}
    ).json()
    r = client.get(f"/api/workspaces/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_get_missing_workspace_404(client: TestClient):
    r = client.get("/api/workspaces/ws_DOESNOTEXIST")
    assert r.status_code == 404


def test_list_workspaces(client: TestClient):
    client.post("/api/workspaces", json={"name": "A", "plan": "public"})
    client.post("/api/workspaces", json={"name": "B", "plan": "private"})
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {w["name"] for w in body} == {"A", "B"}


def test_add_member(client: TestClient):
    ws = client.post("/api/workspaces", json={"name": "A", "plan": "public"}).json()
    r = client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={"user_id": "u_USER0001", "role": "editor"},
    )
    assert r.status_code == 201
    assert r.json() == {
        "workspace_id": ws["id"],
        "user_id": "u_USER0001",
        "role": "editor",
    }


def test_list_members(client: TestClient):
    ws = client.post("/api/workspaces", json={"name": "A", "plan": "public"}).json()
    client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={"user_id": "u_USER0001", "role": "owner"},
    )
    client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={"user_id": "u_USER0002", "role": "viewer"},
    )
    r = client.get(f"/api/workspaces/{ws['id']}/members")
    assert r.status_code == 200
    assert {m["user_id"] for m in r.json()} == {"u_USER0001", "u_USER0002"}


def test_delete_workspace(client: TestClient):
    ws = client.post("/api/workspaces", json={"name": "X", "plan": "public"}).json()
    r = client.delete(f"/api/workspaces/{ws['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/workspaces/{ws['id']}")
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/integration/test_workspaces_api.py -v`
Expected: 7 failures with 404 (router not registered yet).

- [ ] **Step 3: Implement the router**

Create `smadp/api/routes/workspaces.py`:

```python
"""FastAPI router for /api/workspaces (and /api/workspaces/{id}/members)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict

from smadp.schemas.tenancy import Member, Plan, Role, Workspace
from smadp.tenancy import store

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class CreateWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    plan: Plan


class AddMemberBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: Role


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Workspace)
def create_workspace(body: CreateWorkspaceBody) -> Workspace:
    return store.create_workspace(name=body.name, plan=body.plan)


@router.get("", response_model=list[Workspace])
def list_workspaces() -> list[Workspace]:
    return store.list_workspaces()


@router.get("/{workspace_id}", response_model=Workspace)
def get_workspace(workspace_id: str) -> Workspace:
    try:
        return store.get_workspace(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: str) -> Response:
    try:
        store.delete_workspace(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{workspace_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=Member,
)
def add_member(workspace_id: str, body: AddMemberBody) -> Member:
    # Validate workspace exists first.
    try:
        store.get_workspace(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return store.add_member(
        workspace_id=workspace_id, user_id=body.user_id, role=body.role
    )


@router.get("/{workspace_id}/members", response_model=list[Member])
def list_members(workspace_id: str) -> list[Member]:
    try:
        store.get_workspace(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return store.list_members(workspace_id=workspace_id)


__all__ = ["router"]
```

Modify `smadp/api/routes/__init__.py` to register the router:

```python
"""FastAPI route modules for the SMADP REST API."""

from smadp.api.routes import (
    agents,
    chronicle,
    evaluate,
    frameworks,
    health,
    meta,
    sandbox,
    search,
    submit,
    verdicts,
    workspaces,
)

ROUTERS = [
    health.router,
    meta.router,
    agents.router,
    verdicts.router,
    submit.router,
    evaluate.router,
    search.router,
    frameworks.router,
    chronicle.router,
    sandbox.router,
    workspaces.router,
]

__all__ = ["ROUTERS"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/integration/test_workspaces_api.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/api/routes/workspaces.py smadp/api/routes/__init__.py tests/integration/test_workspaces_api.py
git commit -m "feat(api): /api/workspaces router (CRUD + members)"
```

---

## Task 14: Transparency API router

**Files:**
- Create: `smadp/api/routes/transparency.py`
- Create: `tests/integration/test_transparency_api.py`
- Modify: `smadp/api/routes/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_transparency_api.py`:

```python
"""Integration tests for /api/transparency."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.transparency import journal


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def test_list_events_empty(client: TestClient):
    r = client.get("/api/transparency/events")
    assert r.status_code == 200
    assert r.json() == []


def test_list_events_returns_appended(client: TestClient, cfg: Config):
    key = Ed25519PrivateKey.generate()
    journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=key, config=cfg
    )
    journal.append_event(
        event_type="x.b", payload={"k": 2}, signing_key=key, config=cfg
    )
    r = client.get("/api/transparency/events")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert [e["event_type"] for e in body] == ["x.a", "x.b"]


def test_get_event_by_id(client: TestClient, cfg: Config):
    key = Ed25519PrivateKey.generate()
    journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=key, config=cfg
    )
    r = client.get("/api/transparency/events/1")
    assert r.status_code == 200
    assert r.json()["event_type"] == "x.a"


def test_get_missing_event_404(client: TestClient):
    r = client.get("/api/transparency/events/9999")
    assert r.status_code == 404


def test_filter_by_event_type(client: TestClient, cfg: Config):
    key = Ed25519PrivateKey.generate()
    journal.append_event(event_type="x.a", payload={}, signing_key=key, config=cfg)
    journal.append_event(event_type="x.b", payload={}, signing_key=key, config=cfg)
    journal.append_event(event_type="x.a", payload={}, signing_key=key, config=cfg)
    r = client.get("/api/transparency/events?event_type=x.a")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert all(e["event_type"] == "x.a" for e in body)
```

- [ ] **Step 2: Run — expect failures**

Run: `pytest tests/integration/test_transparency_api.py -v`
Expected: 5 failures with 404.

- [ ] **Step 3: Implement the router**

Create `smadp/api/routes/transparency.py`:

```python
"""FastAPI router for /api/transparency — read-only journal access."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from smadp.schemas.transparency import SignedEvent
from smadp.transparency.journal import iter_events

router = APIRouter(prefix="/transparency", tags=["transparency"])


@router.get("/events", response_model=list[SignedEvent])
def list_events(
    event_type: Annotated[
        str | None,
        Query(description="Filter to events of this type (exact match)"),
    ] = None,
) -> list[SignedEvent]:
    out: list[SignedEvent] = []
    for ev in iter_events():
        if event_type is not None and ev.event_type != event_type:
            continue
        out.append(ev)
    return out


@router.get("/events/{event_id}", response_model=SignedEvent)
def get_event(event_id: int) -> SignedEvent:
    for ev in iter_events():
        if ev.id == event_id:
            return ev
    raise HTTPException(status_code=404, detail=f"No event with id {event_id}")


__all__ = ["router"]
```

Modify `smadp/api/routes/__init__.py` to add `transparency` to imports and `ROUTERS`:

```python
"""FastAPI route modules for the SMADP REST API."""

from smadp.api.routes import (
    agents,
    chronicle,
    evaluate,
    frameworks,
    health,
    meta,
    sandbox,
    search,
    submit,
    transparency,
    verdicts,
    workspaces,
)

ROUTERS = [
    health.router,
    meta.router,
    agents.router,
    verdicts.router,
    submit.router,
    evaluate.router,
    search.router,
    frameworks.router,
    chronicle.router,
    sandbox.router,
    workspaces.router,
    transparency.router,
]

__all__ = ["ROUTERS"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/integration/test_transparency_api.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/api/routes/transparency.py smadp/api/routes/__init__.py tests/integration/test_transparency_api.py
git commit -m "feat(api): /api/transparency router (read-only journal access)"
```

---

## Task 15: CLI — `smadp transparency verify`

**Files:**
- Create: `smadp/transparency/cli.py`
- Modify: `smadp/cli.py` — register the `transparency` Click subgroup
- Create: `tests/integration/test_cli_transparency.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_cli_transparency.py`:

```python
"""Integration tests for the smadp transparency CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from smadp.cli import main
from smadp.config import Config
from smadp.transparency import journal


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    return Config()


def _write_pubkey(tmp_path: Path, key: Ed25519PrivateKey) -> Path:
    p = tmp_path / "pub.hex"
    pub_bytes = key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    p.write_text(pub_bytes.hex())
    return p


def test_verify_command_passes_clean_log(tmp_path: Path, cfg: Config):
    key = Ed25519PrivateKey.generate()
    journal.append_event(event_type="x.a", payload={}, signing_key=key, config=cfg)
    journal.append_event(event_type="x.b", payload={}, signing_key=key, config=cfg)
    pub = _write_pubkey(tmp_path, key)

    runner = CliRunner()
    result = runner.invoke(
        main, ["transparency", "verify", "--public-key", str(pub)]
    )
    assert result.exit_code == 0
    assert "OK" in result.output


def test_verify_command_fails_tampered_log(
    tmp_path: Path, cfg: Config, monkeypatch
):
    key = Ed25519PrivateKey.generate()
    journal.append_event(event_type="x.a", payload={}, signing_key=key, config=cfg)
    # Tamper:
    conn = journal._connect(cfg)
    try:
        conn.execute("UPDATE signed_events SET payload = ? WHERE id = 1", ('{"x":1}',))
    finally:
        conn.close()

    pub = _write_pubkey(tmp_path, key)
    runner = CliRunner()
    result = runner.invoke(
        main, ["transparency", "verify", "--public-key", str(pub)]
    )
    assert result.exit_code != 0
    assert "BREAK" in result.output or "invalid" in result.output.lower()


def test_verify_command_empty_log_passes(tmp_path: Path, cfg: Config):
    key = Ed25519PrivateKey.generate()
    pub = _write_pubkey(tmp_path, key)
    runner = CliRunner()
    result = runner.invoke(
        main, ["transparency", "verify", "--public-key", str(pub)]
    )
    assert result.exit_code == 0
```

- [ ] **Step 2: Run — expect failure**

Run: `pytest tests/integration/test_cli_transparency.py -v`
Expected: failures (subgroup not registered).

- [ ] **Step 3: Implement the CLI module**

Create `smadp/transparency/cli.py`:

```python
"""Click subcommands for transparency log: verify, export."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from rich.console import Console

from smadp.config import load_config
from smadp.transparency import journal

console = Console()


@click.group(name="transparency")
def transparency_group() -> None:
    """Inspect and verify the transparency log."""


@transparency_group.command(name="verify")
@click.option(
    "--public-key",
    "public_key_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to a hex-encoded Ed25519 public key (32 bytes raw).",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help="(ignored in v2-D Plan 1; reserved for time-bounded verify in Plan 5)",
)
def verify(public_key_path: Path, since: str | None) -> None:
    """Walk the journal and verify every signature + chain link."""
    pub_hex = public_key_path.read_text().strip()
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
    cfg = load_config()
    report = journal.verify_chain(public_key=pub, config=cfg)
    if report.valid:
        console.print("[green]OK[/green] — transparency chain intact.")
        sys.exit(0)
    else:
        console.print(
            f"[red]BREAK[/red] at event id {report.first_break}: {report.reason}"
        )
        sys.exit(1)


@transparency_group.command(name="export")
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Output JSONL file path.",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help="(ignored in v2-D Plan 1; full export only)",
)
def export(out_path: Path, since: str | None) -> None:
    """Export the transparency log to a JSONL file (cold storage)."""
    cfg = load_config()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for ev in journal.iter_events(config=cfg):
            fh.write(
                json.dumps(
                    ev.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            fh.write("\n")
            count += 1
    console.print(f"Exported [cyan]{count}[/cyan] events to {out_path}")


__all__ = ["transparency_group"]
```

Modify `smadp/cli.py` — find where the existing top-level `main` Click group is defined, and after the existing subgroup registrations add:

```python
from smadp.transparency.cli import transparency_group

main.add_command(transparency_group)
```

(If `smadp/cli.py` does not currently have `main` as a `click.group()` — it does, see `[project.scripts] smadp = "smadp.cli:main"` — or if registration uses a different style, mirror the existing pattern. Run `grep -n "add_command\|@main" smadp/cli.py` to find the right spot.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_cli_transparency.py -v`
Expected: 3 passed.

- [ ] **Step 5: Manual smoke**

Run: `python -m smadp.cli transparency --help`
Expected: shows `verify` and `export` subcommands.

- [ ] **Step 6: Commit**

```bash
git add smadp/transparency/cli.py smadp/cli.py tests/integration/test_cli_transparency.py
git commit -m "feat(cli): smadp transparency verify + export"
```

---

## Task 16: End-to-end integration test

**Files:**
- Create: `tests/integration/test_foundation_e2e.py`

- [ ] **Step 1: Write the e2e test**

Create `tests/integration/test_foundation_e2e.py`:

```python
"""End-to-end test: workspace + BYOK + journal + verify chain.

Walks the full Plan 1 surface in one test:

1. POST /api/workspaces → create workspace
2. Upload BYOK signing key for that workspace
3. Append events to the transparency journal using the BYOK key
4. Verify chain via the same workspace's public key
5. Export the journal to JSONL and re-verify line-by-line
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.tenancy import keys
from smadp.transparency import journal


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


def test_foundation_end_to_end(cfg: Config, tmp_path: Path):
    client = TestClient(create_app(cfg))

    # 1. Create workspace.
    ws = client.post(
        "/api/workspaces", json={"name": "Acme", "plan": "private"}
    ).json()

    # 2. Upload BYOK signing key (programmatic — no API for this in Plan 1).
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=ws["id"], private_key=priv, config=cfg)

    # 3. Append three events to the journal.
    for i in range(3):
        journal.append_event(
            event_type="verdict.created",
            payload={"verdict_id": f"vdt_e2e_{i}", "score": 0.1 * i},
            signing_key=priv,
            config=cfg,
        )

    # 4. Verify chain.
    pub = keys.get_public_key(workspace_id=ws["id"], config=cfg)
    assert pub is not None
    report = journal.verify_chain(public_key=pub, config=cfg)
    assert report.valid is True

    # 5. Pull events via API.
    r = client.get("/api/transparency/events")
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 3

    # 6. Verify the API-returned ordering matches journal iteration.
    assert [ev["event_type"] for ev in listed] == ["verdict.created"] * 3
    assert [ev["payload"]["verdict_id"] for ev in listed] == [
        "vdt_e2e_0",
        "vdt_e2e_1",
        "vdt_e2e_2",
    ]

    # 7. Verify the chain still passes after API reads (read-only must not mutate).
    report2 = journal.verify_chain(public_key=pub, config=cfg)
    assert report2.valid is True
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/integration/test_foundation_e2e.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_foundation_e2e.py
git commit -m "test(foundation): end-to-end workspace + BYOK + journal + verify"
```

---

## Task 17: CI — add transparency-verify smoke step

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Inspect existing CI**

Run: `cat .github/workflows/ci.yml`
Look for the existing `pytest` step. The new step goes after the test step but before the lint step (so a broken chain fails CI even if tests pass).

- [ ] **Step 2: Add a smoke-test step**

We can't directly use `smadp transparency verify` in CI without a populated DB and a public key, so the smoke test runs the verifier against a test-fixture journal generated on the fly. Add this step (insert after the existing `pytest` job step in the matrix):

```yaml
      - name: smoke — transparency verify (empty log returns OK)
        env:
          SMADP_CACHE_DIR: ${{ runner.temp }}/smadp-ci-cache
        run: |
          python -c "
          from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
          from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
          k = Ed25519PrivateKey.generate()
          import pathlib
          p = pathlib.Path('${{ runner.temp }}/pub.hex')
          p.write_text(k.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw).hex())
          "
          python -m smadp.cli transparency verify --public-key "${{ runner.temp }}/pub.hex"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: smoke-test smadp transparency verify on every push"
```

- [ ] **Step 4: Push and confirm CI passes**

```bash
git push
gh run watch
```

Expected: CI green for both Python 3.11 and 3.12 jobs.

---

## Task 18: Final sweep — lint, format, mypy, full test suite

**Files:**
- (none — verifies everything from Tasks 1-17 is consistent with v1's CI gates)

- [ ] **Step 1: Run ruff (lint)**

Run: `ruff check .`
Expected: 0 issues.
If issues: fix them and re-run. Common Plan 1 catches: missing `from __future__ import annotations`, unsorted imports.

- [ ] **Step 2: Run ruff format check**

Run: `ruff format --check .`
Expected: 0 changes needed.
If changes needed: `ruff format .` then commit as `style: ruff format`.

- [ ] **Step 3: Run mypy strict**

Run: `mypy smadp/`
Expected: no errors in new modules.
If new modules trip mypy strict, add them to the `[[tool.mypy.overrides]]` block in `pyproject.toml` ONLY if they are placeholder/orchestration code. Foundation modules (tenancy, transparency) should be fully typed — don't shortcut into the override.

- [ ] **Step 4: Run the full test suite**

Run: `pytest -ra`
Expected: all tests pass; existing v1 tests still green.

- [ ] **Step 5: If anything failed, fix and commit**

If the final sweep surfaces fixes, commit each as `fix(<area>): <what>` before moving on.

- [ ] **Step 6: Final push**

```bash
git push
gh run watch
```

Expected: CI green. Plan 1 complete.

---

## Self-review (engineer should run this before marking the plan done)

- [ ] **Spec coverage check** — open `docs/superpowers/specs/2026-05-03-v2-d-audience-cd-design.md` §6.1, §6.2, §8.1 (workspaces, members, signing_keys, signed_events tables and modules `smadp.tenancy`, `smadp.transparency`). Every Pydantic field, every table column, every public function in those sections is implemented in this plan. The only deferral is real Sigstore client wiring (stubbed in Task 12; replaced in Plan 2).
- [ ] **Scope cuts** — auth (who-is-this-user) is intentionally not implemented; headers `X-SMADP-Workspace` and `X-SMADP-User` are read raw and trusted in Plan 1. A real auth gateway lands in Plan 7 (out of v2-D scope per spec §11).
- [ ] **All 18 tasks committed individually** (not squashed) so the audit log shows the TDD discipline.

---

**Plan 1 ships when CI is green and all 18 tasks are merged. Plan 2 (Passport) can begin immediately.**
