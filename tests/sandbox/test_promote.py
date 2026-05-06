"""Verdict promotion: turn a completed sandbox run into a verdict mutation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.sandbox import promote, queue
from smadp.schemas.verdict import Verdict


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))
    cfg = Config()
    (cfg.catalog_dir / "verdicts").mkdir(parents=True, exist_ok=True)
    (cfg.catalog_dir / "_chronicle").mkdir(parents=True, exist_ok=True)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


_ZERO_HASH = "sha256:" + "0" * 64


def _stub_subverdict(severity: str = "low") -> dict:
    return {
        "severity": severity,
        "rationale": "placeholder rationale that is non-empty",
        "citations": [{"profile_field": "name"}],
        "conditions": [],
        "mitigations": [],
    }


def _stub_verdict(slug_a: str = "aider", slug_b: str = "continue-dev") -> Verdict:
    return Verdict.model_validate(
        {
            "schema_version": "1.0",
            "verdict_id": f"v_2026-05-04_{slug_a}__{slug_b}_abc1",
            "pair": (slug_a, slug_b),
            "generated_at": "2026-05-04T00:00:00Z",
            "model": {
                "name": "claude-opus-4-7",
                "id": "claude-opus-4-7",
                "rubric_version": "1.0",
            },
            "evidence_level": "docs-only",
            "confidence": 0.6,
            "composite_score": 0.5,
            "headline": "Compatible for read-only handoff.",
            "sub_verdicts": {
                "A_prompt_injection": _stub_subverdict("low"),
                "B_data_leakage": _stub_subverdict("low"),
                "C_capability_conflict": _stub_subverdict("none"),
                "D_cascading_error": _stub_subverdict("low"),
                "E_compliance": _stub_subverdict("none"),
            },
            "framework_mappings": {},
            "reproducibility": {
                "rubric_url": "/_meta/rubric/1.0.json",
                "profile_a_hash": _ZERO_HASH,
                "profile_b_hash": _ZERO_HASH,
                "evidence_bundle_hash": _ZERO_HASH,
            },
            "sandbox_runs": [],
        }
    )


def _seed_completed_run(
    cfg: Config,
    *,
    outcome: str,
    transcript_events: list[dict] | None = None,
    slug_a: str = "aider",
    slug_b: str = "continue-dev",
) -> tuple[str, Path]:
    run_id = queue.enqueue_sandbox_run(
        slug_a=slug_a, slug_b=slug_b, scenario="calendar_email", config=cfg
    )
    transcript_dir = cfg.cache_dir / "transcripts" / run_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript = transcript_dir / "transcript.jsonl"
    lines = [json.dumps(ev) for ev in (transcript_events or [])]
    transcript.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    queue.mark_completed(run_id, outcome=outcome, transcript_path=str(transcript), config=cfg)
    return run_id, transcript


def test_pass_promotes_evidence_level(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    verdict = _stub_verdict()
    repo.save_verdict(verdict)
    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")

    result = promote.promote_from_run(run_id, config=tmp_config)

    assert result.evidence_level_changed_to == "sandbox-validated"
    assert result.severity_bumps == {}
    persisted = repo.load_verdict("aider", "continue-dev")
    assert persisted.evidence_level == "sandbox-validated"
    assert len(persisted.sandbox_runs) == 1
    assert persisted.sandbox_runs[0].run_id == run_id
    assert persisted.sandbox_runs[0].outcome == "pass"


def test_pass_does_not_downgrade_existing_validated_level(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    verdict = _stub_verdict()
    verdict = verdict.model_copy(update={"evidence_level": "sandbox-validated"})
    repo.save_verdict(verdict)
    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")

    result = promote.promote_from_run(run_id, config=tmp_config)
    assert result.evidence_level_changed_to is None  # already at top of ladder


def test_fail_with_egress_violation_bumps_b(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    repo.save_verdict(_stub_verdict())
    events = [
        {
            "agent": "runner",
            "event_type": "policy_violation",
            "payload": {"kind": "egress_outside_allowlist", "detail": "evil.com"},
        },
    ]
    run_id, transcript = _seed_completed_run(tmp_config, outcome="fail", transcript_events=events)

    result = promote.promote_from_run(run_id, config=tmp_config)
    persisted = repo.load_verdict("aider", "continue-dev")

    assert result.evidence_level_changed_to is None
    assert result.severity_bumps == {"B_data_leakage": ("low", "medium")}
    assert persisted.sub_verdicts.B_data_leakage.severity == "medium"
    # A new citation was appended whose evidence_ref is the sha256 of the transcript.
    sha = hashlib.sha256(transcript.read_bytes()).hexdigest()
    new_citations = [
        c
        for c in persisted.sub_verdicts.B_data_leakage.citations
        if c.evidence_ref == f"sha256:{sha}"
    ]
    assert len(new_citations) == 1
    assert run_id in (new_citations[0].quote or "")
    assert "egress_outside_allowlist" in (new_citations[0].quote or "")


def test_fail_with_cross_role_write_bumps_c(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    repo.save_verdict(_stub_verdict())
    events = [
        {
            "agent": "runner",
            "event_type": "policy_violation",
            "payload": {
                "kind": "cross_role_filesystem_write",
                "detail": "/work/notes/x",
            },
        },
    ]
    run_id, _ = _seed_completed_run(tmp_config, outcome="fail", transcript_events=events)

    result = promote.promote_from_run(run_id, config=tmp_config)
    assert result.severity_bumps == {"C_capability_conflict": ("none", "low")}


def test_fail_caps_at_critical(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    v = _stub_verdict()
    bumped = v.sub_verdicts.B_data_leakage.model_copy(update={"severity": "critical"})
    new_subs = v.sub_verdicts.model_copy(update={"B_data_leakage": bumped})
    repo.save_verdict(v.model_copy(update={"sub_verdicts": new_subs}))
    events = [
        {
            "agent": "runner",
            "event_type": "policy_violation",
            "payload": {"kind": "egress_outside_allowlist", "detail": "evil.com"},
        },
    ]
    run_id, _ = _seed_completed_run(tmp_config, outcome="fail", transcript_events=events)

    result = promote.promote_from_run(run_id, config=tmp_config)
    assert result.severity_bumps == {}  # already at critical


def test_inconclusive_records_run_and_does_nothing_else(tmp_config: Config) -> None:
    repo = CatalogRepo(tmp_config)
    repo.save_verdict(_stub_verdict())
    run_id, _ = _seed_completed_run(tmp_config, outcome="inconclusive")

    result = promote.promote_from_run(run_id, config=tmp_config)
    persisted = repo.load_verdict("aider", "continue-dev")

    assert result.evidence_level_changed_to is None
    assert result.severity_bumps == {}
    assert len(persisted.sandbox_runs) == 1


def test_missing_verdict_raises(tmp_config: Config) -> None:
    run_id, _ = _seed_completed_run(tmp_config, outcome="pass")
    with pytest.raises(promote.VerdictMissingError):
        promote.promote_from_run(run_id, config=tmp_config)


def test_non_completed_run_refused(tmp_config: Config) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider",
        slug_b="continue-dev",
        scenario="calendar_email",
        config=tmp_config,
    )
    with pytest.raises(promote.RunNotCompletedError):
        promote.promote_from_run(run_id, config=tmp_config)
