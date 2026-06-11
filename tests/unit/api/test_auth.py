"""Tests for operator-token auth on write endpoints (smadp/api/auth.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config

TOKEN = "operator-secret"


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, token: str | None) -> TestClient:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    if token is None:
        monkeypatch.delenv("SMADP_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("SMADP_API_TOKEN", token)
    return TestClient(create_app(Config()))


def test_get_is_open_without_token(tmp_path, monkeypatch):
    # Read endpoints stay public regardless of token configuration.
    client = _client(tmp_path, monkeypatch, token=None)
    assert client.get("/api/workspaces").status_code == 200


def test_write_503_when_no_token_configured(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, token=None)
    r = client.post("/api/workspaces", json={"name": "X", "plan": "public"})
    assert r.status_code == 503


def test_write_401_without_header(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, token=TOKEN)
    r = client.post("/api/workspaces", json={"name": "X", "plan": "public"})
    assert r.status_code == 401


def test_write_401_with_wrong_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, token=TOKEN)
    r = client.post(
        "/api/workspaces",
        json={"name": "X", "plan": "public"},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401


def test_write_succeeds_with_correct_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, token=TOKEN)
    r = client.post(
        "/api/workspaces",
        json={"name": "X", "plan": "public"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 201
