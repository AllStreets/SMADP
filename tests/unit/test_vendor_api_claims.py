"""Unit tests for vendor.api claim endpoints."""

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


def test_create_claim_repo_returns_token(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/claims",
        json={
            "agent_id": "claude-code",
            "method": "repo",
            "evidence_url": "https://github.com/o/r/raw/main",
        },
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["claim"]["id"].startswith("vc_")
    assert body["claim"]["status"] == "pending"
    assert "token" in body
    assert len(body["token"]) >= 32
    assert body["instructions"]["method"] == "repo"
    assert "owner.txt" in body["instructions"]["text"]


def test_create_claim_email_returns_magic_link(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "email", "evidence_url": None},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["instructions"]["method"] == "email"
    assert body["instructions"]["magic_link_url"].startswith(
        "https://smadp.example/vendor/claims/"
    )
    assert "?token=" in body["instructions"]["magic_link_url"]


def test_create_claim_invalid_agent_id_400(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/claims",
        json={"agent_id": "Bad_Slug!", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 422


def test_create_claim_requires_workspace(client: TestClient):
    r = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
    )
    assert r.status_code in {401, 403, 422}


def test_list_claims(client: TestClient, workspace_id: str):
    client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    r = client.get("/api/vendor/claims", headers=_hdrs(workspace_id))
    assert r.status_code == 200
    assert len(r.json()) == 1
    # Token is NEVER returned on list
    assert "token" not in r.json()[0]


@respx.mock
def test_verify_claim_repo_happy_path(client: TestClient, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    token = create.json()["token"]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    r = client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 200
    assert r.json()["claim"]["status"] == "verified"
    assert r.json()["verification"]["verified"] is True


@respx.mock
def test_verify_claim_repo_mismatch_409(client: TestClient, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text="not-the-token")
    )
    r = client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 409
    body = r.json()
    assert body["claim"]["status"] == "pending"
    assert body["verification"]["verified"] is False


def test_revoke_claim(client: TestClient, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    r = client.post(f"/api/vendor/claims/{cid}/revoke", headers=_hdrs(workspace_id))
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"


def test_cross_workspace_404(client: TestClient, cfg: Config, workspace_id: str):
    create = client.post(
        "/api/vendor/claims",
        json={"agent_id": "claude-code", "method": "repo", "evidence_url": "https://github.com/o/r/raw/main"},
        headers=_hdrs(workspace_id),
    )
    cid = create.json()["claim"]["id"]
    other = tenancy.create_workspace(name="O", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=other.id, user_id="u_IJKLMNOP", role=Role.EDITOR, config=cfg)
    r = client.get("/api/vendor/claims", headers=_hdrs(other.id, "u_IJKLMNOP"))
    assert r.status_code == 200
    assert all(c["id"] != cid for c in r.json())
