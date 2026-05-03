"""Smoke tests for the FastAPI app — exercise the public read paths.

The app is built fresh in a fixture so each test gets a clean rate
limiter and job store. The catalog points at the seed data on disk.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config


@pytest.fixture()
def client(tmp_catalog: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_catalog))
    cfg = Config(repo_root=tmp_catalog.parent)
    app = create_app(cfg)
    with TestClient(app) as c:
        yield c


def test_health_ok(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "1.0"
    assert body["rubric_version"] == "1.0"


def test_list_agents_includes_claude_code(client: TestClient) -> None:
    r = client.get("/api/agents", params={"limit": 500})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    slugs = {item["slug"] for item in items}
    assert "claude-code" in slugs


def test_get_agent_returns_profile(client: TestClient) -> None:
    r = client.get("/api/agents/claude-code")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "claude-code"
    assert body["name"] == "Claude Code"


def test_get_agent_404_on_missing(client: TestClient) -> None:
    r = client.get("/api/agents/this-agent-does-not-exist-xyz")
    assert r.status_code == 404


def test_list_verdicts(client: TestClient) -> None:
    r = client.get("/api/verdicts", params={"limit": 500})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["items"], list)
    assert body["page"]["total"] >= 1


def test_get_verdict_first(client: TestClient) -> None:
    list_resp = client.get("/api/verdicts", params={"limit": 1})
    items = list_resp.json()["items"]
    assert items, "no verdicts in seed catalog"
    pair = items[0]["pair"]
    r = client.get(f"/api/verdicts/{pair[0]}/{pair[1]}")
    assert r.status_code == 200
    body = r.json()
    assert body["pair"] == pair


def test_search_returns_results(client: TestClient) -> None:
    r = client.get("/api/search", params={"q": "claude"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "claude"
    refs = {(i["kind"], i["ref"]) for i in body["items"]}
    assert ("profile", "claude-code") in refs


def test_frameworks(client: TestClient) -> None:
    r = client.get("/api/frameworks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "frameworks" in body
    assert isinstance(body["frameworks"], list)


def test_chronicle(client: TestClient) -> None:
    r = client.get("/api/chronicle")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_meta_categories(client: TestClient) -> None:
    """The /meta endpoints expose schema-version-pinned reference data."""
    r = client.get("/api/meta/categories")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_meta_risk_taxonomy(client: TestClient) -> None:
    r = client.get("/api/meta/risk-taxonomy")
    assert r.status_code == 200


def test_health_includes_versions(client: TestClient) -> None:
    """``/health`` is the canonical place for the schema/rubric versions."""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert {"schema_version", "rubric_version", "version"} <= set(body)


def test_rate_limiter_kicks_in_on_writes(tmp_catalog: Path) -> None:
    """The token bucket caps at 60 requests in a 60s window for write paths.

    We exercise the limiter directly (rather than POSTing 61 submissions
    that would each require a profiler the test env may not have).
    """
    cfg = Config(repo_root=tmp_catalog.parent)
    app = create_app(cfg)
    limiter = app.state.rate_limiter
    # Fresh limiter; first 60 calls allowed, 61st refused.
    for i in range(60):
        assert limiter.allow("1.2.3.4"), f"request {i} unexpectedly refused"
    assert not limiter.allow("1.2.3.4")


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_submit_returns_429_after_rate_limit(client: TestClient) -> None:
    """Hammer ``POST /api/agents`` until the rate limiter rejects.

    Pydantic body validation runs before the route body, so we send a
    well-formed body. The profiler subsystem is invoked on a background
    task — the synchronous response just records a queued job; we
    silence the unawaited-coroutine warning the failing background task
    can emit so it doesn't pollute the rate-limiter assertion.
    """
    payload = {
        "urls": ["https://example.com/agent-rate-limit-test"],
        "name": "Rate Limit Test Agent",
        "slug": "rate-limit-test-agent",
    }
    refused = False
    for _ in range(80):
        r = client.post("/api/agents", json=payload)
        if r.status_code == 429:
            refused = True
            break
    assert refused, "rate limiter never returned 429 after 80 attempts"
