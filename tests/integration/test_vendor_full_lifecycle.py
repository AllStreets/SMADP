"""End-to-end vendor lifecycle: claim → verify → response → dispute → resolve."""

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
    ws = tenancy.create_workspace(name="L", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="u_VENDOR01", role=Role.EDITOR, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="u_ADMIN001", role=Role.ADMIN, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def _vendor(ws):
    return {"X-SMADP-Workspace": ws, "X-SMADP-User": "u_VENDOR01"}


def _admin(ws):
    return {"X-SMADP-Workspace": ws, "X-SMADP-User": "u_ADMIN001"}


@respx.mock
def test_full_lifecycle_repo_claim_to_resolved_dispute(client: TestClient, workspace_id: str):
    # 1. Create claim (repo)
    create = client.post(
        "/api/vendor/claims",
        json={
            "agent_id": "claude-code",
            "method": "repo",
            "evidence_url": "https://github.com/o/r/raw/main",
        },
        headers=_vendor(workspace_id),
    )
    assert create.status_code == 201
    cid = create.json()["claim"]["id"]
    token = create.json()["token"]

    # 2. Verify (mock the repo)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    verify = client.post(
        f"/api/vendor/claims/{cid}/verify",
        json={"method": "repo", "evidence": {"repo_url": "https://github.com/o/r/raw/main"}},
        headers=_vendor(workspace_id),
    )
    assert verify.status_code == 200
    assert verify.json()["claim"]["status"] == "verified"

    # 3. Post a response on a verdict
    resp = client.post(
        "/api/vendor/responses",
        json={
            "verdict_id": "vdt_LIFECYCLE",
            "agent_id": "claude-code",
            "body_md": "we have mitigated the issue in v1.2",
        },
        headers=_vendor(workspace_id),
    )
    assert resp.status_code == 201
    rid = resp.json()["id"]

    # 4. List responses
    listed = client.get(
        "/api/vendor/responses",
        params={"verdict_id": "vdt_LIFECYCLE"},
        headers=_vendor(workspace_id),
    )
    assert listed.status_code == 200
    assert any(r["id"] == rid for r in listed.json())

    # 5. File a dispute
    f = client.post(
        "/api/vendor/disputes",
        json={
            "verdict_id": "vdt_LIFECYCLE",
            "agent_id": "claude-code",
            "argument_md": "score should be 0.7 not 0.4 because we shipped patches",
            "requested_outcome": "reeval",
        },
        headers=_vendor(workspace_id),
    )
    assert f.status_code == 201
    did = f.json()["id"]
    assert f.json()["status"] == "triage"

    # 6. Operator triages as substantive
    triage = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "substantive"},
        headers=_admin(workspace_id),
    )
    assert triage.status_code == 200
    assert triage.json()["status"] == "pending_review"
    assert triage.json()["sla_breached_at"] is not None

    # 7. Operator resolves with stands + rationale
    res = client.patch(
        f"/api/vendor/disputes/{did}",
        json={"decision": "stands", "rationale_md": "additional review confirms verdict"},
        headers=_admin(workspace_id),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "resolved_stands"
    assert res.json()["decision_rationale_md"] == "additional review confirms verdict"

    # 8. Cross-workspace isolation: a different workspace cannot see this dispute
    from smadp.config import load_config
    from smadp.tenancy import store as tenancy_store

    cfg = load_config()
    other = tenancy_store.create_workspace(name="O", plan=Plan.PUBLIC, config=cfg)
    tenancy_store.add_member(
        workspace_id=other.id, user_id="u_OTHER001", role=Role.ADMIN, config=cfg
    )
    other_list = client.get(
        "/api/vendor/disputes",
        headers={"X-SMADP-Workspace": other.id, "X-SMADP-User": "u_OTHER001"},
    )
    assert other_list.status_code == 200
    assert all(d["id"] != did for d in other_list.json())
