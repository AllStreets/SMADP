"""Tests for POST /api/refresh — manual enqueue endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.refresh import api as refresh_api
from smadp.refresh import queue
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="R", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(
        workspace_id=ws.id, user_id="u_ADMIN001", role=Role.ADMIN, config=cfg
    )
    tenancy.add_member(
        workspace_id=ws.id, user_id="u_VIEWER01", role=Role.VIEWER, config=cfg
    )
    return ws.id


@pytest.fixture
def client(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("smadp.refresh.api.load_config", lambda: cfg)
    app = create_app(cfg)
    app.include_router(refresh_api.router, prefix="/api")
    return TestClient(app)


def test_post_refresh_enqueues_manual(
    client: TestClient, cfg: Config, workspace_id: str
) -> None:
    resp = client.post(
        "/api/refresh",
        json={"verdict_id": "agent-a__agent-b", "reason": "ops asked"},
        headers={
            "X-SMADP-Workspace": workspace_id,
            "X-SMADP-User": "u_ADMIN001",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["verdict_id"] == "agent-a__agent-b"
    assert body["trigger"] == "manual"
    pending = queue.list_pending(config=cfg)
    assert [p.verdict_id for p in pending] == ["agent-a__agent-b"]
    assert pending[0].trigger_detail["reason"] == "ops asked"
    assert pending[0].trigger_detail["user_id"] == "u_ADMIN001"


def test_post_refresh_requires_admin(
    client: TestClient, workspace_id: str
) -> None:
    resp = client.post(
        "/api/refresh",
        json={"verdict_id": "agent-a__agent-b"},
        headers={
            "X-SMADP-Workspace": workspace_id,
            "X-SMADP-User": "u_VIEWER01",
        },
    )
    assert resp.status_code == 403
