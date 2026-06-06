"""Tests for run_docs_only_tick."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from smadp.autopilot.docs_only_tick import DocsOnlyTickSummary, run_docs_only_tick
from smadp.autopilot.judges.docs_only import JudgeResult
from smadp.autopilot.work_queue import WorkItem, append_items


def _seed_profiles(repo: Path, slugs: list[str]) -> None:
    (repo / "catalog" / "profiles").mkdir(parents=True, exist_ok=True)
    for slug in slugs:
        (repo / "catalog" / "profiles" / f"{slug}.json").write_text(
            json.dumps(
                {
                    "slug": slug,
                    "name": slug.title(),
                    "category": "coding",
                    "evidence_level": "docs-only",
                    "capabilities": {},
                    "docs_urls": [],
                }
            )
        )


def _seed_queue(repo: Path, items: list[WorkItem]) -> None:
    queue = repo / "state" / "docs_only_queue.jsonl"
    append_items(queue, items)


def _seed_autopilot_config(repo: Path, *, runs_per_day: int, dollars_per_day: float) -> None:
    (repo / "config").mkdir(parents=True, exist_ok=True)
    (repo / "config" / "autopilot.yaml").write_text(
        f"runs_per_day: {runs_per_day}\ndollars_per_day: {dollars_per_day}\n"
    )


def _fake_verdict(slug_a: str, slug_b: str) -> dict:
    a, b = sorted([slug_a, slug_b])
    return {
        "schema_version": "1.0",
        "verdict_id": f"v_test_{a}__{b}",
        "pair": [a, b],
        "evidence_level": "docs-only",
        "composite_score": 0.4,
        "model": {"name": "gpt-5.4-mini", "id": "gpt-5.4-mini", "rubric_version": "1.0"},
        "headline": "h",
        "sub_verdicts": {},
        "framework_mappings": {},
        "confidence": 0.7,
        "generated_at": "2026-06-06T00:00:00Z",
    }


def _judge_factory(verdicts: list[dict]):
    fake = MagicMock()
    def evaluate(work, *, profiles):
        return JudgeResult(verdict=verdicts.pop(0), cost_usd=0.04)
    fake.evaluate = evaluate
    fake.cost_per_call_usd = 0.04
    fake.name = "docs_only"
    return fake


def test_tick_drains_and_publishes(tmp_path: Path) -> None:
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)
    _seed_profiles(repo, ["aider", "cursor"])
    _seed_queue(
        repo,
        [
            WorkItem(
                pair=("aider", "cursor"),
                requested_judge="docs_only",
                judge_version="v1",
                priority=0.9,
                enqueued_at="2026-06-06T00:00:00Z",
            )
        ],
    )
    judge = _judge_factory([_fake_verdict("aider", "cursor")])

    summary = run_docs_only_tick(
        repo_root=repo,
        judge=judge,
        batch_size=10,
    )
    assert isinstance(summary, DocsOnlyTickSummary)
    assert summary.published == 1
    assert summary.reason == "ok"
    assert list((repo / "catalog" / "verdicts").glob("*.json"))


def test_tick_respects_budget(tmp_path: Path) -> None:
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=1, dollars_per_day=5.0)
    _seed_profiles(repo, ["aider", "cursor", "claude-code"])
    _seed_queue(
        repo,
        [
            WorkItem(("aider", "cursor"), "docs_only", "v1", 0.9, "2026-06-06T00:00:00Z"),
            WorkItem(("aider", "claude-code"), "docs_only", "v1", 0.8, "2026-06-06T00:00:00Z"),
        ],
    )
    judge = _judge_factory([_fake_verdict("aider", "cursor"), _fake_verdict("aider", "claude-code")])

    summary = run_docs_only_tick(repo_root=repo, judge=judge, batch_size=10)
    assert summary.published == 1  # only one run allowed today


def test_tick_returns_no_work_when_queue_empty(tmp_path: Path) -> None:
    _seed_autopilot_config(tmp_path, runs_per_day=10, dollars_per_day=5.0)
    summary = run_docs_only_tick(
        repo_root=tmp_path,
        judge=_judge_factory([]),
        batch_size=10,
    )
    assert summary.reason == "no_work"
    assert summary.published == 0


def test_tick_pause_short_circuits(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "PAUSED").touch()
    summary = run_docs_only_tick(
        repo_root=tmp_path,
        judge=_judge_factory([]),
        batch_size=10,
    )
    assert summary.reason == "paused"


def test_tick_logs_failure_and_continues(tmp_path: Path) -> None:
    """A judge raising on one item should not poison the rest of the batch."""
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)
    _seed_profiles(repo, ["a", "b", "c", "d"])
    _seed_queue(
        repo,
        [
            WorkItem(("a", "b"), "docs_only", "v1", 0.9, "2026-06-06T00:00:00Z"),
            WorkItem(("c", "d"), "docs_only", "v1", 0.8, "2026-06-06T00:00:00Z"),
        ],
    )

    calls = [0]
    def evaluate(work, *, profiles):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("boom")
        return JudgeResult(verdict=_fake_verdict(*work.pair), cost_usd=0.04)
    judge = MagicMock(name="docs_only", cost_per_call_usd=0.04)
    judge.evaluate = evaluate

    summary = run_docs_only_tick(repo_root=repo, judge=judge, batch_size=10)
    assert summary.published == 1
    assert summary.failed == 1
    assert (repo / "state" / "judge_errors.jsonl").exists()
