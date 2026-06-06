"""Docs-only tick: drain work queue -> judge -> publish -> update budget.

Mirrors the existing sandbox ``tick.py`` but operates against the docs-only
work queue and a Python judge instead of the sandbox runner. Reuses
``BudgetState`` so daily caps are shared with the sandbox path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from smadp.autopilot.budget import (
    BudgetState,
    can_enqueue,
    load_budget,
    record_run_actual,
)
from smadp.autopilot.config import load_autopilot_config
from smadp.autopilot.pause import is_paused
from smadp.autopilot.publishers.policy import PolicyPublisher
from smadp.autopilot.work_queue import drain_items, read_all_items

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DocsOnlyTickSummary:
    published: int
    failed: int
    reason: str   # "ok" | "paused" | "budget_exhausted" | "no_work"


def _load_profiles(profiles_dir: Path) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    if not profiles_dir.exists():
        return profiles
    for path in profiles_dir.glob("*.json"):
        try:
            profile = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        slug = profile.get("slug") or path.stem
        profiles[slug] = profile
    return profiles


def _log_failure(state_dir: Path, *, pair: tuple, judge_name: str, error: str) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "pair": list(pair),
        "judge": judge_name,
        "error": error,
        "attempted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with (state_dir / "judge_errors.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def run_docs_only_tick(
    *,
    repo_root: Path,
    judge: Any,
    batch_size: int = 10,
) -> DocsOnlyTickSummary:
    state_dir = repo_root / "state"
    queue_path = state_dir / "docs_only_queue.jsonl"

    if is_paused(state_dir):
        log.info("docs_only_tick.paused")
        return DocsOnlyTickSummary(published=0, failed=0, reason="paused")

    cfg = load_autopilot_config(repo_root / "config" / "autopilot.yaml")
    budget_path = state_dir / "budget.json"
    budget = load_budget(budget_path)

    if budget.runs_today >= cfg.runs_per_day:
        return DocsOnlyTickSummary(published=0, failed=0, reason="budget_exhausted")
    if budget.dollars_today >= cfg.dollars_per_day:
        return DocsOnlyTickSummary(published=0, failed=0, reason="budget_exhausted")

    items = read_all_items(queue_path)
    if not items:
        return DocsOnlyTickSummary(published=0, failed=0, reason="no_work")

    profiles = _load_profiles(repo_root / "catalog" / "profiles")
    publisher = PolicyPublisher(
        catalog_root=repo_root / "catalog",
        auto_publish={
            "docs-only": True,
            "profile-verified": True,
            "sandbox-run": False,
        },
    )

    cost_per_call = float(getattr(judge, "cost_per_call_usd", 0.04))
    cap_by_runs = cfg.runs_per_day - budget.runs_today
    cap_by_dollars = int(max(0, (cfg.dollars_per_day - budget.dollars_today) // cost_per_call))
    effective = max(0, min(batch_size, cap_by_runs, cap_by_dollars))

    drained = drain_items(queue_path, limit=effective)
    published = 0
    failed = 0
    for work in drained:
        if not can_enqueue(load_budget(budget_path), cfg, expected_cost=cost_per_call):
            # Budget moved while we were running — bank what we did and stop.
            break
        try:
            result = judge.evaluate(work, profiles=profiles)
            publisher.commit(result.verdict)
            record_run_actual(budget_path, dollars=float(result.cost_usd))
            published += 1
        except Exception as exc:
            failed += 1
            judge_name = getattr(judge, "name", "docs_only")
            # MagicMock(name=...) stores the name kwarg on the mock itself, not
            # as a plain string attribute; force to str so json.dumps doesn't
            # choke on a MagicMock object.
            _log_failure(
                state_dir,
                pair=work.pair,
                judge_name=str(judge_name) if not isinstance(judge_name, str) else judge_name,
                error=repr(exc),
            )
            log.warning("docs_only_tick.judge_failed", pair=work.pair, error=repr(exc))
    if published == 0 and failed == 0:
        return DocsOnlyTickSummary(published=0, failed=0, reason="no_work")
    return DocsOnlyTickSummary(published=published, failed=failed, reason="ok")
