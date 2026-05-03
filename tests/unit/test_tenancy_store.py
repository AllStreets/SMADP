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
