"""Chain composer driver — composes authored chains into pending/chains/."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.autopilot.config import AutopilotConfig
from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.schemas import Chain, Verdict
from smadp.utils.slug import sort_pair


def _sub(severity: str = "low") -> dict:
    return {
        "severity": severity,
        "rationale": "Stub.",
        "citations": [{"quote": "stub"}],
        "conditions": [],
        "mitigations": [],
    }


def _verdict(a: str, b: str, *, confidence: float, sevs: dict[str, str]) -> Verdict:
    a, b = sort_pair(a, b)
    return Verdict.model_validate(
        {
            "schema_version": "1.0",
            "participants": [a, b],
            "verdict_id": f"v_2026-01-01_{a}__{b}_abcd",
            "generated_at": "2026-01-01T00:00:00Z",
            "model": {"id": "gpt-x", "name": "gpt-x", "rubric_version": "1.0"},
            "evidence_level": "profile-verified",
            "confidence": confidence,
            "composite_score": 0.3,
            "headline": "stub headline",
            "sub_verdicts": {
                "A_prompt_injection": _sub(sevs.get("A", "none")),
                "B_data_leakage": _sub(sevs.get("B", "none")),
                "C_capability_conflict": _sub(sevs.get("C", "none")),
                "D_cascading_error": _sub(sevs.get("D", "low")),
                "E_compliance": _sub(sevs.get("E", "none")),
            },
            "reproducibility": {
                "rubric_url": "/_meta/rubric/1.0.json",
                "profile_a_hash": "sha256:" + "0" * 64,
                "profile_b_hash": "sha256:" + "0" * 64,
                "evidence_bundle_hash": "sha256:" + "0" * 64,
            },
        }
    )


def _authored_chain(chain_id: str = "c_demo-loop") -> Chain:
    return Chain.model_validate(
        {
            "schema_version": "1.0",
            "chain_id": chain_id,
            "name": chain_id,
            "topology": "linear",
            "participants": [
                {"slug": "agent-aa", "role": "planner"},
                {"slug": "agent-bb", "role": "executor"},
                {"slug": "agent-cc", "role": "critic"},
            ],
            "edges": [
                {"from": "agent-aa", "to": "agent-bb", "channel": "filesystem",
                 "carries": ["pii"]},
                {"from": "agent-bb", "to": "agent-cc", "channel": "filesystem",
                 "carries": ["pii"]},
            ],
            "headline": "stub.",
            "sub_verdicts": {
                "A_prompt_injection": _sub(),
                "B_data_leakage": _sub(),
                "C_capability_conflict": _sub(),
                "D_cascading_error": _sub(),
                "E_compliance": _sub(),
            },
            "framework_mappings": {},
            "first_seen_at": "2026-05-04T00:00:00Z",
            "last_refreshed_at": "2026-05-04T00:00:00Z",
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


def _seed(cfg: Config, *, high_b: bool = False) -> None:
    repo = CatalogRepo(cfg)
    repo.save_chain(_authored_chain())
    repo.save_verdict(
        _verdict("agent-aa", "agent-bb", confidence=0.9,
                 sevs={"B": "high" if high_b else "low", "D": "low"})
    )
    repo.save_verdict(
        _verdict("agent-bb", "agent-cc", confidence=0.85,
                 sevs={"B": "medium", "D": "medium"})
    )


def test_composes_authored_chain_into_pending(cfg: Config) -> None:
    from smadp.autopilot.chain_composer import compose_authored_chains

    _seed(cfg)
    summary = compose_authored_chains(
        repo_root=cfg.repo_root, config=cfg, autopilot_cfg=AutopilotConfig()
    )
    assert summary.disabled is False
    assert summary.composed >= 1

    repo = CatalogRepo(cfg)
    pending = repo.list_pending_chains()
    assert len(pending) >= 1
    cand = pending[0]
    assert cand.composition_method == "deterministic-v1"
    assert cand.composed_from
    assert cand.confidence is not None and 0.0 <= cand.confidence <= 1.0
    assert cand.composite_score is not None


def test_kill_switch_disables_composition(cfg: Config) -> None:
    from smadp.autopilot.chain_composer import compose_authored_chains

    _seed(cfg)
    summary = compose_authored_chains(
        repo_root=cfg.repo_root,
        config=cfg,
        autopilot_cfg=AutopilotConfig(chain_composition_enabled=False),
    )
    assert summary.disabled is True
    assert summary.composed == 0
    assert CatalogRepo(cfg).list_pending_chains() == []


def test_low_confidence_flags_needs_judge(cfg: Config) -> None:
    from smadp.autopilot.chain_composer import compose_authored_chains

    _seed(cfg)
    # threshold above the composed confidence (min(0.9,0.85)=0.85) forces flagging.
    summary = compose_authored_chains(
        repo_root=cfg.repo_root,
        config=cfg,
        autopilot_cfg=AutopilotConfig(chain_publish_confidence_threshold=0.99),
    )
    assert summary.needs_judge >= 1


# --------------------------------------------------------------- Task 9 judge


class _FakeJudge:
    """Symbols-only judge mock. Returns bands + headline, never a number."""

    def __init__(self, severities: dict[str, str], headline: str = "judged headline"):
        self.calls = 0
        self._severities = severities
        self._headline = headline

    async def confirm_chain(self, candidate):  # noqa: ANN001
        self.calls += 1
        from smadp.autopilot.chain_composer import ChainJudgement

        return ChainJudgement(severities=dict(self._severities), headline=self._headline)


def test_judge_keeps_composite_python_computed(cfg: Config) -> None:
    from smadp.autopilot.chain_composer import (
        compose_authored_chains,
        confirm_low_confidence_chains,
    )

    _seed(cfg)
    compose_authored_chains(
        repo_root=cfg.repo_root,
        config=cfg,
        autopilot_cfg=AutopilotConfig(chain_publish_confidence_threshold=0.99),
    )
    judge = _FakeJudge(
        {
            "A_prompt_injection": "high",
            "B_data_leakage": "critical",
            "C_capability_conflict": "high",
            "D_cascading_error": "high",
            "E_compliance": "medium",
        }
    )
    result = confirm_low_confidence_chains(
        repo_root=cfg.repo_root,
        config=cfg,
        autopilot_cfg=AutopilotConfig(
            chain_publish_confidence_threshold=0.99, chain_judge_batch_max=10
        ),
        judge=judge,
    )
    assert result.judged >= 1
    assert judge.calls >= 1
    cand = CatalogRepo(cfg).list_pending_chains()[0]
    assert cand.composite_score is not None and 0.0 <= cand.composite_score <= 1.0


def test_judge_batch_is_capped(cfg: Config) -> None:
    from smadp.autopilot.chain_composer import (
        compose_authored_chains,
        confirm_low_confidence_chains,
    )

    _seed(cfg)
    compose_authored_chains(
        repo_root=cfg.repo_root,
        config=cfg,
        autopilot_cfg=AutopilotConfig(chain_publish_confidence_threshold=0.99),
    )
    judge = _FakeJudge({k: "low" for k in (
        "A_prompt_injection", "B_data_leakage", "C_capability_conflict",
        "D_cascading_error", "E_compliance")})
    confirm_low_confidence_chains(
        repo_root=cfg.repo_root,
        config=cfg,
        autopilot_cfg=AutopilotConfig(
            chain_publish_confidence_threshold=0.99, chain_judge_batch_max=0
        ),
        judge=judge,
    )
    assert judge.calls == 0


def test_no_judge_calls_when_kill_switch_off(cfg: Config) -> None:
    from smadp.autopilot.chain_composer import confirm_low_confidence_chains

    _seed(cfg)
    judge = _FakeJudge({k: "low" for k in (
        "A_prompt_injection", "B_data_leakage", "C_capability_conflict",
        "D_cascading_error", "E_compliance")})
    result = confirm_low_confidence_chains(
        repo_root=cfg.repo_root,
        config=cfg,
        autopilot_cfg=AutopilotConfig(chain_composition_enabled=False),
        judge=judge,
    )
    assert result.disabled is True
    assert judge.calls == 0
