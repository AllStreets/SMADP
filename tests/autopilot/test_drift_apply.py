"""Capability-drift refresh hook: stale flags + chronicle + history append."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.autopilot.drift import apply_capability_drift
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.schemas import Profile, Verdict
from smadp.utils.slug import sort_pair

BASE = {
    "name": "X",
    "vendor": {"type": "company", "handle": "h"},
    "source_type": "open-source",
    "category": "coding",
    "verification": {
        "status": "verified",
        "verified_at": "2026-01-01T00:00:00Z",
        "method": "manual-authoring",
    },
    "first_seen_at": "2026-01-01T00:00:00Z",
    "last_refreshed_at": "2026-06-01T00:00:00Z",
}


def _profile(slug: str, **caps) -> Profile:
    return Profile.model_validate({**BASE, "slug": slug, "capabilities": caps})


def _sub() -> dict:
    return {
        "severity": "low",
        "rationale": "stub",
        "citations": [{"quote": "x"}],
        "conditions": [],
        "mitigations": [],
    }


def _verdict(a: str, b: str) -> Verdict:
    a, b = sort_pair(a, b)
    return Verdict.model_validate(
        {
            "schema_version": "1.0",
            "participants": [a, b],
            "verdict_id": f"v_2026-01-01_{a}__{b}_abcd",
            "generated_at": "2026-01-01T00:00:00Z",
            "model": {"id": "gpt-x", "name": "gpt-x", "rubric_version": "1.0"},
            "evidence_level": "profile-verified",
            "confidence": 0.8,
            "composite_score": 0.3,
            "headline": "stub",
            "sub_verdicts": {
                k: _sub()
                for k in (
                    "A_prompt_injection",
                    "B_data_leakage",
                    "C_capability_conflict",
                    "D_cascading_error",
                    "E_compliance",
                )
            },
            "reproducibility": {
                "rubric_url": "/_meta/rubric/1.0.json",
                "profile_a_hash": "sha256:" + "0" * 64,
                "profile_b_hash": "sha256:" + "0" * 64,
                "evidence_bundle_hash": "sha256:" + "0" * 64,
            },
        }
    )


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config(repo_root=tmp_path)
    cfg.ensure_dirs()
    return cfg


def test_expansion_stales_verdicts_and_appends_history(cfg: Config) -> None:
    repo = CatalogRepo(cfg)
    repo.save_profile(_profile("agent-xx"))  # no execute_shell
    repo.save_profile(_profile("agent-yy"))
    repo.save_verdict(_verdict("agent-xx", "agent-yy"))

    new = _profile("agent-xx", execute_shell=True)
    summary = apply_capability_drift(config=cfg, new_profile=new)

    assert summary.expanded is True
    v = repo.load_verdict(*sort_pair("agent-xx", "agent-yy"))
    assert v.stale_reason == "capability_drift"
    saved = repo.load_profile("agent-xx")
    assert len(saved.capability_history) == 1

    drift_events = [e for e in Chronicle(cfg).iter_events() if e.event == "capability_drift"]
    assert any(e.slug == "agent-xx" for e in drift_events)


def test_no_change_is_noop(cfg: Config) -> None:
    repo = CatalogRepo(cfg)
    repo.save_profile(_profile("agent-zz", execute_shell=True))

    summary = apply_capability_drift(
        config=cfg, new_profile=_profile("agent-zz", execute_shell=True)
    )
    assert summary.expanded is False
    assert summary.changed is False
    saved = repo.load_profile("agent-zz")
    assert saved.capability_history == []
