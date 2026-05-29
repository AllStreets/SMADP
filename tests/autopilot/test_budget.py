from datetime import datetime, timezone, timedelta
from pathlib import Path
from smadp.autopilot.budget import (
    BudgetState,
    load_budget,
    save_budget,
    can_enqueue,
    record_run_actual,
)
from smadp.autopilot.config import AutopilotConfig


def test_loads_default_when_missing(tmp_path: Path) -> None:
    state = load_budget(tmp_path / "budget.json")
    assert state.runs_today == 0
    assert state.dollars_today == 0.0


def test_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "budget.json"
    # Use today's date so the lazy daily-reset in load_budget doesn't fire.
    state = BudgetState(date=_today(), runs_today=3, dollars_today=1.25)
    save_budget(p, state)
    loaded = load_budget(p)
    assert loaded == state


def test_daily_reset(tmp_path: Path) -> None:
    """A loaded state with yesterday's date resets to zero on access."""
    p = tmp_path / "budget.json"
    save_budget(p, BudgetState(date="2025-01-01", runs_today=99, dollars_today=99.0))
    state = load_budget(p)
    assert state.runs_today == 0
    assert state.dollars_today == 0.0


def test_can_enqueue_blocks_at_run_cap(tmp_path: Path) -> None:
    state = BudgetState(date=_today(), runs_today=10, dollars_today=0.5)
    cfg = AutopilotConfig(runs_per_day=10, dollars_per_day=5.0)
    assert can_enqueue(state, cfg, expected_cost=0.10) is False


def test_can_enqueue_blocks_at_dollar_cap(tmp_path: Path) -> None:
    state = BudgetState(date=_today(), runs_today=2, dollars_today=4.95)
    cfg = AutopilotConfig(runs_per_day=10, dollars_per_day=5.00)
    assert can_enqueue(state, cfg, expected_cost=0.10) is False


def test_can_enqueue_allows_within_caps(tmp_path: Path) -> None:
    state = BudgetState(date=_today(), runs_today=1, dollars_today=1.0)
    cfg = AutopilotConfig(runs_per_day=10, dollars_per_day=5.0)
    assert can_enqueue(state, cfg, expected_cost=0.10) is True


def test_record_run_actual_increments(tmp_path: Path) -> None:
    p = tmp_path / "budget.json"
    save_budget(p, BudgetState(date=_today(), runs_today=2, dollars_today=1.0))
    record_run_actual(p, dollars=0.50)
    state = load_budget(p)
    assert state.runs_today == 3
    assert state.dollars_today == 1.50


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
