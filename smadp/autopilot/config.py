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
    # S2.1 chain-composition kill switch + thresholds. When disabled, the
    # composer driver short-circuits and writes no pending chain candidates.
    chain_composition_enabled: bool = True
    chain_publish_confidence_threshold: float = 0.6
    chain_judge_batch_max: int = 10
    # S2.3 triage kill switch. When disabled, the pair planner falls back to
    # plain composite-product ordering (no triage re-ranking).
    triage_enabled: bool = True
    # High-confidence auto-publish lane. docs-only verdicts at/above this
    # confidence are promoted straight to the public catalog (still signed via the
    # normal approve path); everything below stays in catalog/pending/ for the
    # operator gate. 0.0 disables the lane (pure human gate — the prior behaviour).
    auto_publish_docs_only_min_confidence: float = 0.0


def _as_bool(raw_value: object, default: bool) -> bool:
    """Coerce a YAML scalar to bool, tolerating YAML 1.1 on/off/yes/no."""
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    text = str(raw_value).strip().lower()
    if text in {"true", "yes", "on", "1"}:
        return True
    if text in {"false", "no", "off", "0"}:
        return False
    return default


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
    chain_block = raw.get("chain_composition") or {}
    triage_block = raw.get("triage") or {}
    return AutopilotConfig(
        runs_per_day=int(raw.get("runs_per_day", 10)),
        dollars_per_day=float(raw.get("dollars_per_day", 5.0)),
        tripwires=_parse_tripwires(raw.get("tripwires")),
        chain_composition_enabled=_as_bool(chain_block.get("enabled"), True),
        chain_publish_confidence_threshold=float(
            chain_block.get("publish_confidence_threshold", 0.6)
        ),
        chain_judge_batch_max=int(chain_block.get("judge_batch_max", 10)),
        triage_enabled=_as_bool(triage_block.get("enabled"), True),
        auto_publish_docs_only_min_confidence=float(
            (raw.get("auto_publish") or {}).get("docs_only_min_confidence", 0.0)
        ),
    )
