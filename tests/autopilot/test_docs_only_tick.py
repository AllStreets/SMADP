"""Tests for run_docs_only_tick."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

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


def _seed_autopilot_config(
    repo: Path,
    *,
    runs_per_day: int,
    dollars_per_day: float,
    auto_publish_min: float | None = None,
) -> None:
    (repo / "config").mkdir(parents=True, exist_ok=True)
    text = f"runs_per_day: {runs_per_day}\ndollars_per_day: {dollars_per_day}\n"
    if auto_publish_min is not None:
        text += f"auto_publish:\n  docs_only_min_confidence: {auto_publish_min}\n"
    (repo / "config" / "autopilot.yaml").write_text(text)


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


def _docs_only_judge_factory(verdicts: list[dict]):
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
    judge = _docs_only_judge_factory([_fake_verdict("aider", "cursor")])

    summary = run_docs_only_tick(
        repo_root=repo,
        judges={"docs_only": judge},
        batch_size=10,
    )
    assert isinstance(summary, DocsOnlyTickSummary)
    assert summary.published == 1
    assert summary.reason == "ok"
    # docs-only verdicts no longer auto-publish to catalog/verdicts/ — they
    # land in catalog/pending/ for operator review (see PolicyPublisher
    # auto_publish config in docs_only_tick.run_docs_only_tick).
    assert list((repo / "catalog" / "pending").glob("*.json"))


def _one_pair_queue(repo: Path) -> None:
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


def test_tick_auto_publishes_high_confidence(tmp_path: Path, monkeypatch) -> None:
    """With the lane armed, a verdict at/above threshold is sent through approve()."""
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0, auto_publish_min=0.70)
    _one_pair_queue(repo)
    verdict = _fake_verdict("aider", "cursor")
    verdict["confidence"] = 0.72  # >= 0.70 threshold
    judge = _docs_only_judge_factory([verdict])

    calls: list[str] = []
    monkeypatch.setattr(
        "smadp.autopilot.docs_only_tick.approve",
        lambda *, key, repo_root: calls.append(key),
    )
    summary = run_docs_only_tick(repo_root=repo, judges={"docs_only": judge}, batch_size=10)
    assert summary.published == 1
    assert summary.auto_published == 1
    assert len(calls) == 1  # the strong verdict was routed to the operator-gate bypass


def test_tick_gates_low_confidence_when_lane_armed(tmp_path: Path, monkeypatch) -> None:
    """A verdict below threshold is never sent through approve() — stays in pending/."""
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0, auto_publish_min=0.70)
    _one_pair_queue(repo)
    verdict = _fake_verdict("aider", "cursor")
    verdict["confidence"] = 0.50  # below 0.70 threshold
    judge = _docs_only_judge_factory([verdict])

    calls: list[str] = []
    monkeypatch.setattr(
        "smadp.autopilot.docs_only_tick.approve",
        lambda *, key, repo_root: calls.append(key),
    )
    summary = run_docs_only_tick(repo_root=repo, judges={"docs_only": judge}, batch_size=10)
    assert summary.published == 1
    assert summary.auto_published == 0
    assert calls == []  # gated for human review
    assert list((repo / "catalog" / "pending").glob("*.json"))


def test_tick_lane_disabled_by_default(tmp_path: Path, monkeypatch) -> None:
    """Without the config block, the lane is off — even a high-confidence verdict gates."""
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)  # no auto_publish
    _one_pair_queue(repo)
    verdict = _fake_verdict("aider", "cursor")
    verdict["confidence"] = 0.95
    judge = _docs_only_judge_factory([verdict])

    calls: list[str] = []
    monkeypatch.setattr(
        "smadp.autopilot.docs_only_tick.approve",
        lambda *, key, repo_root: calls.append(key),
    )
    summary = run_docs_only_tick(repo_root=repo, judges={"docs_only": judge}, batch_size=10)
    assert summary.auto_published == 0
    assert calls == []


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
    judge = _docs_only_judge_factory(
        [_fake_verdict("aider", "cursor"), _fake_verdict("aider", "claude-code")]
    )

    summary = run_docs_only_tick(repo_root=repo, judges={"docs_only": judge}, batch_size=10)
    assert summary.published == 1


def test_tick_returns_no_work_when_queue_empty(tmp_path: Path) -> None:
    _seed_autopilot_config(tmp_path, runs_per_day=10, dollars_per_day=5.0)
    summary = run_docs_only_tick(
        repo_root=tmp_path,
        judges={"docs_only": _docs_only_judge_factory([])},
        batch_size=10,
    )
    assert summary.reason == "no_work"
    assert summary.published == 0


def test_tick_pause_short_circuits(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "PAUSED").touch()
    summary = run_docs_only_tick(
        repo_root=tmp_path,
        judges={"docs_only": _docs_only_judge_factory([])},
        batch_size=10,
    )
    assert summary.reason == "paused"


def test_tick_logs_failure_and_continues(tmp_path: Path) -> None:
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
    judge.name = "docs_only"
    judge.evaluate = evaluate

    summary = run_docs_only_tick(repo_root=repo, judges={"docs_only": judge}, batch_size=10)
    assert summary.published == 1
    assert summary.failed == 1
    assert (repo / "state" / "judge_errors.jsonl").exists()


# ---- NEW TESTS for multi-judge dispatch ----


def test_tick_routes_profile_enrich_to_commit_profile(tmp_path: Path) -> None:
    """Enrichment items write to catalog/profiles/, not catalog/verdicts/."""
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)
    (repo / "catalog" / "profiles").mkdir(parents=True)
    (repo / "catalog" / "profiles" / "aider.json").write_text(
        json.dumps(
            {
                "slug": "aider",
                "evidence_level": "unverified-profile",
                "onexus": {"source_github": "p/aider"},
            }
        )
    )
    _seed_queue(
        repo,
        [WorkItem(("aider", "aider"), "profile_enrich", "v1", 0.9, "2026-06-06T00:00:00Z")],
    )

    enriched = {
        "slug": "aider",
        "evidence_level": "docs-only",
        "capabilities": {"execute_shell": True},
    }
    enrich_judge = MagicMock()
    enrich_judge.name = "profile_enrich"
    enrich_judge.cost_per_call_usd = 0.04
    enrich_judge.evaluate = MagicMock(return_value=JudgeResult(verdict=enriched, cost_usd=0.04))

    summary = run_docs_only_tick(
        repo_root=repo,
        judges={"profile_enrich": enrich_judge},
        batch_size=10,
    )
    assert summary.published == 1
    written = json.loads((repo / "catalog" / "profiles" / "aider.json").read_text())
    assert written["evidence_level"] == "docs-only"
    assert written["capabilities"]["execute_shell"] is True
    assert not list((repo / "catalog" / "verdicts").glob("*.json"))


def test_tick_skips_when_judge_not_registered(tmp_path: Path) -> None:
    repo = tmp_path
    _seed_autopilot_config(repo, runs_per_day=10, dollars_per_day=5.0)
    _seed_queue(
        repo,
        [WorkItem(("a", "b"), "mystery_judge", "v1", 0.9, "2026-06-06T00:00:00Z")],
    )
    summary = run_docs_only_tick(
        repo_root=repo,
        judges={},
        batch_size=10,
    )
    assert summary.published == 0
    assert summary.failed == 1
