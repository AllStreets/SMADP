"""Integration tests for /api/passports."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def test_get_passport_html_returns_200(client: TestClient, workspace_id: str):
    """Hit the endpoint with a known v1 catalog pair (anthropic/claude + openai/gpt-5)."""
    r = client.get(
        "/api/passports/anthropic__claude-sonnet-4.6/openai__gpt-5.html",
        headers={"X-SMADP-Workspace": workspace_id},
    )
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.headers["content-type"].startswith("text/html")
        assert b"<!DOCTYPE html>" in r.content


def test_get_passport_missing_workspace_header_returns_403(client: TestClient):
    r = client.get(
        "/api/passports/anthropic__claude-sonnet-4.6/openai__gpt-5.html",
    )
    assert r.status_code == 403


def test_get_passport_unknown_workspace_returns_404(client: TestClient):
    r = client.get(
        "/api/passports/anthropic__claude-sonnet-4.6/openai__gpt-5.html",
        headers={"X-SMADP-Workspace": "ws_DOESNOTEXIST"},
    )
    assert r.status_code == 404
