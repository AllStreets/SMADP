"""Autopilot tick: plan the next batch of sandbox runs.

Order of operations:
1. If state/PAUSED exists -> return ("paused", 0)
2. Load budget; if exhausted -> return ("budget_exhausted", 0)
3. Drain catalog/priority.yaml entries that haven't been enqueued recently.
4. If priority drained AND budget remains -> compute coverage gaps and enqueue.
5. Record each enqueue in state/coverage.json.

The function is idempotent: re-running it with no state change enqueues nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from smadp.autopilot.budget import can_enqueue, load_budget
from smadp.autopilot.config import load_autopilot_config
from smadp.autopilot.coverage import has_recent_enqueue, record_enqueued
from smadp.autopilot.pause import is_paused
from smadp.autopilot.priority import load_priority
from smadp.config import Config
from smadp.sandbox import queue as sandbox_queue
from smadp.sandbox.binding import ScenarioBindingError, bind_scenario, load_adapter_capabilities
from smadp.sandbox.scenarios.loader import ScenarioLoadError, load_scenario

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TickSummary:
    enqueued: int
    would_enqueue: int
    reason: str  # "ok" | "paused" | "budget_exhausted" | "no_work"


_DEFAULT_EXPECTED_COST = 0.10  # conservative -- refine per-adapter in v2


def run_tick(*, repo_root: Path, dry_run: bool) -> TickSummary:
    state_dir = repo_root / "state"
    if is_paused(state_dir):
        log.info("autopilot.tick.paused")
        return TickSummary(enqueued=0, would_enqueue=0, reason="paused")

    autopilot_cfg = load_autopilot_config(repo_root / "config" / "autopilot.yaml")
    budget_path = state_dir / "budget.json"
    coverage_path = state_dir / "coverage.json"
    budget = load_budget(budget_path)

    if budget.runs_today >= autopilot_cfg.runs_per_day:
        return TickSummary(enqueued=0, would_enqueue=0, reason="budget_exhausted")
    if budget.dollars_today >= autopilot_cfg.dollars_per_day:
        return TickSummary(enqueued=0, would_enqueue=0, reason="budget_exhausted")

    # H2: build the sandbox Config directly from the repo_root param. Calling
    # load_config() would silently fall back to SMADP_REPO_ROOT/cwd and ignore
    # the test fixture's tmp_path.
    sandbox_config = Config(repo_root=repo_root)
    enqueued = 0
    would_enqueue = 0
    remaining_budget = autopilot_cfg.runs_per_day - budget.runs_today

    for entry in load_priority(repo_root / "catalog" / "priority.yaml"):
        if enqueued + would_enqueue >= remaining_budget:
            break
        scenario_name = entry["scenario"]
        agent_slugs = entry["agents"]

        if has_recent_enqueue(coverage_path, scenario=scenario_name, participants=agent_slugs):
            continue
        if not can_enqueue(budget, autopilot_cfg, expected_cost=_DEFAULT_EXPECTED_COST):
            break

        try:
            scenario = load_scenario(scenario_name)
            agents = {
                slug: load_adapter_capabilities(slug, config=sandbox_config) for slug in agent_slugs
            }
            binding = bind_scenario(scenario, agents=agents)
        # Narrow catch -- these are "this entry isn't bindable right now",
        # distinct from genuine bugs (KeyError on a malformed priority entry,
        # TypeError from a refactor, etc.). Let unexpected exceptions propagate
        # so they surface as stack traces instead of silent reason="no_work".
        except (
            ScenarioBindingError,
            ScenarioLoadError,
            FileNotFoundError,
            ValueError,
        ) as exc:
            log.warning(
                "autopilot.tick.priority_skip",
                scenario=scenario_name,
                agents=agent_slugs,
                error=repr(exc),
            )
            continue

        if dry_run:
            would_enqueue += 1
            continue

        sandbox_queue.enqueue_nary(
            config=sandbox_config,
            scenario=scenario_name,
            participants=[
                {"role": role, "slug": slug} for role, slug in binding.role_to_slug.items()
            ],
        )
        record_enqueued(coverage_path, scenario=scenario_name, participants=agent_slugs)
        enqueued += 1

    # Coverage-gap fallback is deferred to a follow-up sub-task once we have
    # a real catalog. For v1, priority-only is sufficient to drive the smoke.
    if enqueued == 0 and would_enqueue == 0:
        return TickSummary(enqueued=0, would_enqueue=0, reason="no_work")
    return TickSummary(enqueued=enqueued, would_enqueue=would_enqueue, reason="ok")
