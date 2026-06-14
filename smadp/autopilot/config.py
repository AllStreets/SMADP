from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


_VALID_TRIPWIRE_MODES = frozenset({"enabled", "log_only", "off"})


@dataclass(frozen=True)
class AutopilotConfig:
    runs_per_day: int = 10
    dollars_per_day: float = 5.0
    # S1.2 kill switch for the tripwire engine:
    #   enabled  — trips halt the run (default)
    #   log_only — trips are recorded as evidence but do not halt
    #   off       — the engine never checks
    tripwires: str = "enabled"


def _parse_tripwires(raw_value: object) -> str:
    """Parse the ``tripwires`` kill switch, failing safe to ``enabled``.

    Any unknown/missing value resolves to ``enabled`` so a typo never silently
    disarms the live interdiction layer.
    """
    # YAML 1.1 coerces bare ``off``/``on`` to booleans. Map them back so the
    # kill switch reads naturally in the config file.
    if raw_value is False:
        return "off"
    if raw_value is True:
        return "enabled"
    value = str(raw_value).strip().lower() if raw_value is not None else "enabled"
    return value if value in _VALID_TRIPWIRE_MODES else "enabled"


def load_autopilot_config(path: Path) -> AutopilotConfig:
    if not path.exists():
        return AutopilotConfig()
    raw = yaml.safe_load(path.read_text("utf-8")) or {}
    return AutopilotConfig(
        runs_per_day=int(raw.get("runs_per_day", 10)),
        dollars_per_day=float(raw.get("dollars_per_day", 5.0)),
        tripwires=_parse_tripwires(raw.get("tripwires")),
    )
