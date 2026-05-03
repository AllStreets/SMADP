"""Integration tests for the /api/webhooks/subscriptions endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="WH", plan=Plan.PUBLIC, config=cfg)
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def test_create_subscription_returns_secret_once(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
        json={"url": "https://example.com/wh", "event_types": ["passport.generated"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["subscription"]["id"].startswith("sub_")
    assert body["subscription"]["url"] == "https://example.com/wh"
    assert body["subscription"]["active"] is True
    assert isinstance(body["secret"], str) and len(body["secret"]) >= 32


def test_create_subscription_rejects_bad_url(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
        json={"url": "ftp://example.com/wh", "event_types": ["passport.generated"]},
    )
    assert r.status_code == 422


def test_create_subscription_requires_workspace_header(client: TestClient):
    r = client.post(
        "/api/webhooks/subscriptions",
        json={"url": "https://example.com/wh", "event_types": ["passport.generated"]},
    )
    assert r.status_code == 403


def test_list_subscriptions_for_workspace(client: TestClient, workspace_id: str):
    for url in ("https://a/wh", "https://b/wh"):
        client.post(
            "/api/webhooks/subscriptions",
            headers={"X-SMADP-Workspace": workspace_id},
            json={"url": url, "event_types": ["passport.generated"]},
        )
    r = client.get(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert {s["url"] for s in items} == {"https://a/wh", "https://b/wh"}
    # Secret never appears in list responses.
    assert all("secret" not in s for s in items)


def test_delete_subscription_deactivates(client: TestClient, workspace_id: str):
    r = client.post(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
        json={"url": "https://example.com/wh", "event_types": ["passport.generated"]},
    )
    sub_id = r.json()["subscription"]["id"]
    d = client.delete(
        f"/api/webhooks/subscriptions/{sub_id}",
        headers={"X-SMADP-Workspace": workspace_id},
    )
    assert d.status_code == 204
    listed = client.get(
        "/api/webhooks/subscriptions",
        headers={"X-SMADP-Workspace": workspace_id},
    ).json()
    assert all(s["active"] is False for s in listed if s["id"] == sub_id)


def test_delete_unknown_subscription_returns_404(client: TestClient, workspace_id: str):
    r = client.delete(
        "/api/webhooks/subscriptions/sub_NOPE0000",
        headers={"X-SMADP-Workspace": workspace_id},
    )
    assert r.status_code == 404
