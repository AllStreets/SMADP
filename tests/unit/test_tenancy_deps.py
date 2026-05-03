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
        headers={"X-SMADP-Workspace": ws.id, "X-SMADP-User": "u_NONMEMB1"},
    )
    assert r.status_code == 403
