"""Read-only chain composition endpoint: GET /api/chains/{id}/composition."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.schemas import Chain, Verdict
from smadp.utils.slug import sort_pair


def _sub(sev: str = "low") -> dict:
    return {"severity": sev, "rationale": "stub", "citations": [{"quote": "x"}],
            "conditions": [], "mitigations": []}


def _verdict(a: str, b: str, *, sev: str) -> Verdict:
    a, b = sort_pair(a, b)
    return Verdict.model_validate({
        "schema_version": "1.0", "participants": [a, b],
        "verdict_id": f"v_2026-01-01_{a}__{b}_abcd",
        "generated_at": "2026-01-01T00:00:00Z",
        "model": {"id": "gpt-x", "name": "gpt-x", "rubric_version": "1.0"},
        "evidence_level": "profile-verified", "confidence": 0.9,
        "composite_score": 0.3, "headline": "stub",
        "sub_verdicts": {k: _sub(sev) for k in (
            "A_prompt_injection", "B_data_leakage", "C_capability_conflict",
            "D_cascading_error", "E_compliance")},
        "reproducibility": {"rubric_url": "/_meta/rubric/1.0.json",
                            "profile_a_hash": "sha256:" + "0" * 64,
                            "profile_b_hash": "sha256:" + "0" * 64,
                            "evidence_bundle_hash": "sha256:" + "0" * 64}})


def _chain() -> Chain:
    return Chain.model_validate({
        "schema_version": "1.0", "chain_id": "c_route-demo", "name": "demo",
        "topology": "linear",
        "participants": [
            {"slug": "agent-aa", "role": "planner"},
            {"slug": "agent-bb", "role": "executor"},
            {"slug": "agent-cc", "role": "critic"},
        ],
        "edges": [
            {"from": "agent-aa", "to": "agent-bb", "channel": "filesystem", "carries": ["pii"]},
            {"from": "agent-bb", "to": "agent-cc", "channel": "filesystem", "carries": ["pii"]},
        ],
        "headline": "stub.",
        "sub_verdicts": {k: _sub() for k in (
            "A_prompt_injection", "B_data_leakage", "C_capability_conflict",
            "D_cascading_error", "E_compliance")},
        "framework_mappings": {},
        "first_seen_at": "2026-05-04T00:00:00Z", "last_refreshed_at": "2026-05-04T00:00:00Z",
    })


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config(repo_root=tmp_path)
    cfg.ensure_dirs()
    repo = CatalogRepo(cfg)
    repo.save_chain(_chain())
    repo.save_verdict(_verdict("agent-aa", "agent-bb", sev="high"))
    repo.save_verdict(_verdict("agent-bb", "agent-cc", sev="medium"))
    return TestClient(create_app(cfg))


def test_composition_route_returns_computed_fields(client: TestClient) -> None:
    resp = client.get("/api/chains/c_route-demo/composition")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("composite_score", "confidence", "max_severity", "severities", "composed_from"):
        assert key in body
    assert 0.0 <= body["composite_score"] <= 1.0
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["composed_from"]


def test_composition_route_404_for_unknown(client: TestClient) -> None:
    resp = client.get("/api/chains/c_missing-id/composition")
    assert resp.status_code == 404
