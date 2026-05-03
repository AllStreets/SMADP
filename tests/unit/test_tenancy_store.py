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
