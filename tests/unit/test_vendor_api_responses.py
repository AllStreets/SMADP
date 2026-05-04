"""Unit tests for /api/vendor/responses."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_PUBLIC_BASE_URL", "https://smadp.example")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="u_ABCDEFGH", role=Role.EDITOR, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def _hdrs(workspace_id: str, user_id: str = "u_ABCDEFGH") -> dict[str, str]:
    return {"X-SMADP-Workspace": workspace_id, "X-SMADP-User": user_id}


def test_post_response_requires_verified_claim(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/responses",
        json={"verdict_id": "vdt_X", "agent_id": "claude-code", "body_md": "hello"},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 403
    assert "verified claim" in r.json()["detail"].lower()


@respx.mock
def test_post_response_after_verify(client: TestClient, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={
            "agent_id": "claude-code",
            "method": "repo",
            "evidence_url": "https://github.com/o/r/raw/main",
        },
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    token = create.json()["token"]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_hdrs(workspace_id),
    )
    r = client.post(
        "/api/vendor/responses",
        json={"verdict_id": "vdt_X", "agent_id": "claude-code", "body_md": "we mitigated"},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 201
    assert r.json()["body_md"] == "we mitigated"


def test_list_responses_for_verdict(client: TestClient, workspace_id: str):
    r = client.get(
        "/api/vendor/responses", params={"verdict_id": "vdt_X"}, headers=_hdrs(workspace_id)
    )
    assert r.status_code == 200
    assert r.json() == []
