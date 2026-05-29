from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from smadp.autopilot.config import AutopilotConfig


@dataclass(frozen=True)
class BudgetState:
    date: str
    runs_today: int
    dollars_today: float


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_budget(path: Path) -> BudgetState:
    if not path.exists():
        return BudgetState(date=_today_str(), runs_today=0, dollars_today=0.0)
    raw = json.loads(path.read_text("utf-8"))
    state = BudgetState(
        date=raw.get("date", _today_str()),
        runs_today=int(raw.get("runs_today", 0)),
        dollars_today=float(raw.get("dollars_today", 0.0)),
    )
    today = _today_str()
    if state.date != today:
        # Lazy daily reset.
        state = BudgetState(date=today, runs_today=0, dollars_today=0.0)
        save_budget(path, state)
    return state


def save_budget(path: Path, state: BudgetState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state)) + "\n", encoding="utf-8")


def can_enqueue(state: BudgetState, cfg: AutopilotConfig, *, expected_cost: float) -> bool:
    if state.runs_today >= cfg.runs_per_day:
        return False
    if state.dollars_today + expected_cost > cfg.dollars_per_day:
        return False
    return True


def record_run_actual(path: Path, *, dollars: float) -> None:
    state = load_budget(path)
    new_state = BudgetState(
        date=state.date,
        runs_today=state.runs_today + 1,
        dollars_today=state.dollars_today + dollars,
    )
    save_budget(path, new_state)
