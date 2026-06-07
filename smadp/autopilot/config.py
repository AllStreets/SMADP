from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True)
class AutopilotConfig:
    runs_per_day: int = 10
    dollars_per_day: float = 5.0


def load_autopilot_config(path: Path) -> AutopilotConfig:
    if not path.exists():
        return AutopilotConfig()
    raw = yaml.safe_load(path.read_text("utf-8")) or {}
    return AutopilotConfig(
        runs_per_day=int(raw.get("runs_per_day", 10)),
        dollars_per_day=float(raw.get("dollars_per_day", 5.0)),
    )
