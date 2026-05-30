"""Tick orchestrator: priority drain + coverage gap + budget + pause."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.autopilot.budget import BudgetState, load_budget, save_budget
from smadp.autopilot.coverage import has_recent_enqueue
from smadp.autopilot.tick import run_tick


def _seed_priority(repo: Path, entries: list[dict]) -> None:
    (repo / "catalog").mkdir(parents=True, exist_ok=True)
    (repo / "catalog" / "priority.yaml").write_text(
        "priority:\n" + "\n".join(f"  - {json.dumps(e)}" for e in entries)
    )


def _seed_autopilot_config(repo: Path, *, runs_per_day: int, dollars_per_day: float) -> None:
    (repo / "config").mkdir(parents=True, exist_ok=True)
    (repo / "config" / "autopilot.yaml").write_text(
        f"runs_per_day: {runs_per_day}\ndollars_per_day: {dollars_per_day}\n"
    )


def test_tick_does_nothing_when_paused(autopilot_repo, capsys) -> None:
    (autopilot_repo / "state").mkdir(exist_ok=True)
    (autopilot_repo / "state" / "PAUSED").touch()

    summary = run_tick(repo_root=autopilot_repo, dry_run=False)

    assert summary.enqueued == 0
    assert summary.reason == "paused"


def test_tick_does_nothing_when_run_cap_exhausted(autopilot_repo) -> None:
    _seed_autopilot_config(autopilot_repo, runs_per_day=2, dollars_per_day=5.0)
    save_budget(
        autopilot_repo / "state" / "budget.json",
        BudgetState(date=_today(), runs_today=2, dollars_today=0.5),
    )
    _seed_priority(autopilot_repo, [{"scenario": "s", "agents": ["a", "b"]}])

    summary = run_tick(repo_root=autopilot_repo, dry_run=False)
    assert summary.enqueued == 0
    assert summary.reason == "budget_exhausted"


def test_tick_enqueues_priority_first(autopilot_repo) -> None:
    """When priority has entries, tick enqueues them before any coverage work."""
    _seed_autopilot_config(autopilot_repo, runs_per_day=5, dollars_per_day=5.0)
    _seed_priority(
        autopilot_repo,
        [{"scenario": "calendar_email", "agents": ["aider", "autogen"]}],
    )

    summary = run_tick(repo_root=autopilot_repo, dry_run=False)

    assert summary.enqueued >= 1
    assert has_recent_enqueue(
        autopilot_repo / "state" / "coverage.json",
        scenario="calendar_email",
        participants=["aider", "autogen"],
    )


def test_tick_is_idempotent(autopilot_repo) -> None:
    """A second tick with no state change adds no new queue rows."""
    _seed_autopilot_config(autopilot_repo, runs_per_day=5, dollars_per_day=5.0)
    _seed_priority(
        autopilot_repo,
        [{"scenario": "calendar_email", "agents": ["aider", "autogen"]}],
    )

    first = run_tick(repo_root=autopilot_repo, dry_run=False)
    second = run_tick(repo_root=autopilot_repo, dry_run=False)

    assert first.enqueued >= 1
    assert second.enqueued == 0


def test_tick_dry_run_does_not_write(autopilot_repo) -> None:
    _seed_autopilot_config(autopilot_repo, runs_per_day=5, dollars_per_day=5.0)
    _seed_priority(
        autopilot_repo,
        [{"scenario": "calendar_email", "agents": ["aider", "autogen"]}],
    )

    summary = run_tick(repo_root=autopilot_repo, dry_run=True)

    assert summary.would_enqueue >= 1
    assert not (autopilot_repo / "state" / "coverage.json").exists()


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture
def autopilot_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp repo with minimal structure for tick to operate on."""
    # Create the directory structure tick expects.
    (tmp_path / "state").mkdir()
    (tmp_path / "catalog" / "verdicts").mkdir(parents=True)
    (tmp_path / "catalog" / "pending").mkdir()
    (tmp_path / "adapters").mkdir()

    # Copy 2 real adapter mcp.json files in so binder can run.
    for slug in ("aider", "autogen"):
        src = Path(__file__).resolve().parents[2] / "adapters" / slug
        dst = tmp_path / "adapters" / slug
        if src.exists():
            dst.mkdir()
            (dst / "mcp.json").write_text((src / "mcp.json").read_text())

    # Scope the sandbox-queue sqlite db to this tmp repo too so we don't pollute
    # the real platformdirs cache or interfere with other tests/runs.
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))

    return tmp_path
