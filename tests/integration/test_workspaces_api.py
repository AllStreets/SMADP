"""Integration tests for /api/workspaces."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return TestClient(create_app(Config()))


def test_create_workspace(client: TestClient):
    r = client.post(
        "/api/workspaces",
        json={"name": "Acme Corp", "plan": "private"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Acme Corp"
    assert body["plan"] == "private"
    assert body["id"].startswith("ws_")


def test_get_workspace(client: TestClient):
    created = client.post("/api/workspaces", json={"name": "X", "plan": "public"}).json()
    r = client.get(f"/api/workspaces/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_get_missing_workspace_404(client: TestClient):
    r = client.get("/api/workspaces/ws_DOESNOTEXIST")
    assert r.status_code == 404


def test_list_workspaces(client: TestClient):
    client.post("/api/workspaces", json={"name": "A", "plan": "public"})
    client.post("/api/workspaces", json={"name": "B", "plan": "private"})
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {w["name"] for w in body} == {"A", "B"}


def test_add_member(client: TestClient):
    ws = client.post("/api/workspaces", json={"name": "A", "plan": "public"}).json()
    r = client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={"user_id": "u_USER0001", "role": "editor"},
    )
    assert r.status_code == 201
    assert r.json() == {
        "workspace_id": ws["id"],
        "user_id": "u_USER0001",
        "role": "editor",
    }


def test_list_members(client: TestClient):
    ws = client.post("/api/workspaces", json={"name": "A", "plan": "public"}).json()
    client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={"user_id": "u_USER0001", "role": "owner"},
    )
    client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={"user_id": "u_USER0002", "role": "viewer"},
    )
    r = client.get(f"/api/workspaces/{ws['id']}/members")
    assert r.status_code == 200
    assert {m["user_id"] for m in r.json()} == {"u_USER0001", "u_USER0002"}


def test_delete_workspace(client: TestClient):
    ws = client.post("/api/workspaces", json={"name": "X", "plan": "public"}).json()
    r = client.delete(f"/api/workspaces/{ws['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/workspaces/{ws['id']}")
    assert r.status_code == 404
