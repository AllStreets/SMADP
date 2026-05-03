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
