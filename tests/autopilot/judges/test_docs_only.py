"""Tests for DocsOnlyJudge."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smadp.autopilot.judges.docs_only import DocsOnlyJudge, JudgeResult
from smadp.autopilot.work_queue import WorkItem


def _wi() -> WorkItem:
    return WorkItem(
        pair=("aider", "cursor"),
        requested_judge="docs_only",
        judge_version="v1",
        priority=0.9,
        enqueued_at="2026-06-06T00:00:00Z",
    )


_FAKE_TOOL_INPUT = {
    "headline": "Both auto-edit; modest capability conflict.",
    "confidence": 0.7,
    "evidence_level": "docs-only",
    "sub_verdicts": {
        "A_prompt_injection": {
            "severity": "low",
            "rationale": "r",
            "citations": [{"profile_field": "agent_a.capabilities"}],
            "conditions": [],
            "mitigations": [],
        },
        "B_data_leakage": {
            "severity": "low",
            "rationale": "r",
            "citations": [{"profile_field": "agent_a.capabilities"}],
            "conditions": [],
            "mitigations": [],
        },
        "C_capability_conflict": {
            "severity": "medium",
            "rationale": "r",
            "citations": [{"profile_field": "agent_a.capabilities"}],
            "conditions": [],
            "mitigations": [],
        },
        "D_cascading_error": {
            "severity": "low",
            "rationale": "r",
            "citations": [{"profile_field": "agent_a.capabilities"}],
            "conditions": [],
            "mitigations": [],
        },
        "E_compliance": {
            "severity": "low",
            "rationale": "r",
            "citations": [{"profile_field": "agent_a.capabilities"}],
            "conditions": [],
            "mitigations": [],
        },
    },
    "framework_mappings": {},
}


def _fake_client():
    fake = SimpleNamespace()
    fake.judge_pair = AsyncMock(
        return_value=SimpleNamespace(tool_input=_FAKE_TOOL_INPUT, raw_response=None)
    )
    return fake


@pytest.fixture
def rubric_path(tmp_path: Path) -> Path:
    p = tmp_path / "rubric.json"
    p.write_text('{"rubric": "stub"}')
    return p


def test_judge_returns_docs_only_verdict(rubric_path: Path) -> None:
    profiles = {
        "aider": {"slug": "aider", "name": "Aider"},
        "cursor": {"slug": "cursor", "name": "Cursor"},
    }
    judge = DocsOnlyJudge(client=_fake_client(), model="gpt-5.4-mini", rubric_path=rubric_path)
    result: JudgeResult = judge.evaluate(_wi(), profiles=profiles)

    verdict = result.verdict
    assert verdict["pair"] == ["aider", "cursor"]
    assert verdict["evidence_level"] == "docs-only"
    assert verdict["schema_version"] == "1.0"
    assert verdict["model"]["name"] == "gpt-5.4-mini"
    assert 0.0 <= verdict["composite_score"] <= 1.0
    assert "verdict_id" in verdict
    assert set(verdict["sub_verdicts"].keys()) == {
        "A_prompt_injection",
        "B_data_leakage",
        "C_capability_conflict",
        "D_cascading_error",
        "E_compliance",
    }


def test_judge_cost_is_recorded(rubric_path: Path) -> None:
    profiles = {"aider": {"slug": "aider"}, "cursor": {"slug": "cursor"}}
    judge = DocsOnlyJudge(client=_fake_client(), model="gpt-5.4-mini", rubric_path=rubric_path)
    result = judge.evaluate(_wi(), profiles=profiles)
    assert result.cost_usd > 0
    assert result.cost_usd <= judge.cost_per_call_usd * 2


def test_judge_verdict_id_is_deterministic(rubric_path: Path) -> None:
    """Re-judging the same pair with the same version yields the same hash suffix."""
    profiles = {"aider": {"slug": "aider"}, "cursor": {"slug": "cursor"}}
    judge_a = DocsOnlyJudge(client=_fake_client(), model="gpt-5.4-mini", rubric_path=rubric_path)
    judge_b = DocsOnlyJudge(client=_fake_client(), model="gpt-5.4-mini", rubric_path=rubric_path)
    id_a = judge_a.evaluate(_wi(), profiles=profiles).verdict["verdict_id"]
    id_b = judge_b.evaluate(_wi(), profiles=profiles).verdict["verdict_id"]
    # last underscore-delimited token is the hash digest
    assert id_a.rsplit("_", 1)[-1] == id_b.rsplit("_", 1)[-1]


def test_judge_missing_profile_raises(rubric_path: Path) -> None:
    judge = DocsOnlyJudge(client=_fake_client(), model="gpt-5.4-mini", rubric_path=rubric_path)
    with pytest.raises(KeyError):
        judge.evaluate(_wi(), profiles={"aider": {}})  # cursor missing


def test_clamp_headline_bounds_to_schema_max() -> None:
    from smadp.autopilot.judges.docs_only import _HEADLINE_MAX, _clamp_headline

    short = "short headline"
    assert _clamp_headline(short) == short

    long = "word " * 80  # ~400 chars, over the 240 cap
    clamped = _clamp_headline(long)
    assert len(clamped) <= _HEADLINE_MAX
    assert clamped.endswith("…")
    assert not clamped.endswith(" …")  # cut on a word boundary, no trailing space
