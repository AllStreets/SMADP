"""Unit tests for /api/vendor/disputes."""

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
    tenancy.add_member(workspace_id=ws.id, user_id="u_IJKLMNOP", role=Role.ADMIN, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def _hdrs(workspace_id: str, user_id: str = "u_ABCDEFGH") -> dict[str, str]:
    return {"X-SMADP-Workspace": workspace_id, "X-SMADP-User": user_id}


@respx.mock
def _verify_claim(client, workspace_id) -> None:
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
    client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_hdrs(workspace_id),
    )


def test_file_dispute_requires_verified_claim(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 403


def test_file_dispute_after_verify(client: TestClient, workspace_id: str):
    _verify_claim(client, workspace_id)
    r = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest because ...",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "triage"
    assert body["id"].startswith("dsp_")


def test_triage_substantive_then_resolve_stands(client: TestClient, workspace_id: str):
    _verify_claim(client, workspace_id)
    f = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest because ...",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    did = f.json()["id"]
    op = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "substantive"},
        headers=_hdrs(workspace_id, "u_IJKLMNOP"),
    )
    assert op.status_code == 200
    assert op.json()["status"] == "pending_review"
    assert op.json()["sla_breached_at"] is not None

    res = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "stands", "rationale_md": "evidence reviewed; verdict confirmed"},
        headers=_hdrs(workspace_id, "u_IJKLMNOP"),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "resolved_stands"


def test_triage_requires_admin(client: TestClient, workspace_id: str):
    _verify_claim(client, workspace_id)
    f = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest because ...",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    did = f.json()["id"]
    op = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "substantive"},
        headers=_hdrs(workspace_id, "u_ABCDEFGH"),
    )
    assert op.status_code == 403


def test_invalid_transition_409(client: TestClient, workspace_id: str):
    _verify_claim(client, workspace_id)
    f = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_X",
            "agent_id": "claude-code",
            "argument_md": "we contest because ...",
            "requested_outcome": "reeval",
        },
        headers=_hdrs(workspace_id),
    )
    did = f.json()["id"]
    res = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "stands", "rationale_md": "x"},
        headers=_hdrs(workspace_id, "u_IJKLMNOP"),
    )
    assert res.status_code == 409
    assert "invalid" in res.json()["detail"].lower()
