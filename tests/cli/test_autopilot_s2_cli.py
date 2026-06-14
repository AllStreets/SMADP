"""S2 autopilot/analyzer CLI commands: compose-chains, approve-chain, triage-train."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from smadp.catalog.repo import CatalogRepo
from smadp.cli import cli
from smadp.config import Config
from smadp.schemas import Chain, Profile, Verdict
from smadp.utils.slug import sort_pair

PBASE = {
    "name": "X", "vendor": {"type": "company", "handle": "h"},
    "source_type": "open-source", "category": "coding",
    "verification": {"status": "verified", "verified_at": "2026-01-01T00:00:00Z",
                     "method": "manual-authoring"},
    "first_seen_at": "2026-01-01T00:00:00Z", "last_refreshed_at": "2026-01-01T00:00:00Z",
}


def _sub(sev: str = "low") -> dict:
    return {"severity": sev, "rationale": "stub", "citations": [{"quote": "x"}],
            "conditions": [], "mitigations": []}


def _profile(slug: str, **caps) -> Profile:
    return Profile.model_validate({**PBASE, "slug": slug, "capabilities": caps})


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
        "schema_version": "1.0", "chain_id": "c_cli-demo", "name": "demo",
        "topology": "linear",
        "participants": [
            {"slug": "agent-aa", "role": "planner"},
            {"slug": "agent-bb", "role": "executor"},
            {"slug": "agent-cc", "role": "critic"},
        ],
        "edges": [
            {"from": "agent-aa", "to": "agent-bb", "channel": "filesystem"},
            {"from": "agent-bb", "to": "agent-cc", "channel": "filesystem"},
        ],
        "headline": "stub.",
        "sub_verdicts": {k: _sub() for k in (
            "A_prompt_injection", "B_data_leakage", "C_capability_conflict",
            "D_cascading_error", "E_compliance")},
        "framework_mappings": {},
        "first_seen_at": "2026-05-04T00:00:00Z", "last_refreshed_at": "2026-05-04T00:00:00Z",
    })


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config(repo_root=tmp_path)
    cfg.ensure_dirs()
    repo = CatalogRepo(cfg)
    repo.save_chain(_chain())
    repo.save_profile(_profile("agent-aa", execute_shell=True))
    repo.save_profile(_profile("agent-bb"))
    repo.save_profile(_profile("agent-cc"))
    repo.save_verdict(_verdict("agent-aa", "agent-bb", sev="high"))
    repo.save_verdict(_verdict("agent-bb", "agent-cc", sev="medium"))
    return cfg.catalog_dir


def test_compose_chains_and_approve_chain(catalog: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["--catalog", str(catalog), "autopilot", "compose-chains"])
    assert r.exit_code == 0, r.output

    cfg = Config(repo_root=catalog.parent)
    repo = CatalogRepo(cfg)
    pending = repo.list_pending_chains()
    assert pending
    chain_id = pending[0].chain_id

    r2 = runner.invoke(
        cli, ["--catalog", str(catalog), "autopilot", "approve-chain", chain_id]
    )
    assert r2.exit_code == 0, r2.output
    assert repo.load_chain(chain_id).chain_id == chain_id


def test_triage_train_writes_artifact(catalog: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "triage_out.json"
    r = runner.invoke(
        cli,
        ["--catalog", str(catalog), "analyzer", "triage-train",
         "--out", str(out), "--seed", "5", "--version", "v1"],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
