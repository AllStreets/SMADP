"""Integration tests for /api/transparency."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.transparency import journal


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def test_list_events_empty(client: TestClient):
    r = client.get("/api/transparency/events")
    assert r.status_code == 200
    assert r.json() == []


def test_list_events_returns_appended(client: TestClient, cfg: Config):
    key = Ed25519PrivateKey.generate()
    journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=key, config=cfg
    )
    journal.append_event(
        event_type="x.b", payload={"k": 2}, signing_key=key, config=cfg
    )
    r = client.get("/api/transparency/events")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert [e["event_type"] for e in body] == ["x.a", "x.b"]


def test_get_event_by_id(client: TestClient, cfg: Config):
    key = Ed25519PrivateKey.generate()
    journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=key, config=cfg
    )
    r = client.get("/api/transparency/events/1")
    assert r.status_code == 200
    assert r.json()["event_type"] == "x.a"


def test_get_missing_event_404(client: TestClient):
    r = client.get("/api/transparency/events/9999")
    assert r.status_code == 404


def test_filter_by_event_type(client: TestClient, cfg: Config):
    key = Ed25519PrivateKey.generate()
    journal.append_event(event_type="x.a", payload={}, signing_key=key, config=cfg)
    journal.append_event(event_type="x.b", payload={}, signing_key=key, config=cfg)
    journal.append_event(event_type="x.a", payload={}, signing_key=key, config=cfg)
    r = client.get("/api/transparency/events?event_type=x.a")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert all(e["event_type"] == "x.a" for e in body)
