"""Decide which scenario role each adapter in a pair plays.

A scenario declares two roles, each with `required_capabilities`. An adapter
declares its capabilities in `mcp.json` under the `capabilities` block. This
module finds an assignment of (slug → role) such that every role's required
capabilities are satisfied by its assigned adapter, then returns the chosen
(role_a, role_b) pair so the queue and runner can persist it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smadp.config import Config, load_config
from smadp.sandbox.scenarios.loader import AgentRole, Scenario


class ScenarioBindingError(RuntimeError):
    """Raised when no assignment of (slug → role) satisfies the scenario."""


@dataclass(frozen=True)
class BindingResult:
    """The chosen role for slug_a and slug_b respectively."""

    role_a: str
    role_b: str


def _adapter_satisfies_role(role: AgentRole, caps: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Return (ok, missing_capability_name)."""
    for cap in role.required_capabilities:
        value = caps.get(cap)
        if cap == "network_egress":
            if value is None or value == "none":
                return False, cap
        else:
            if not bool(value):
                return False, cap
    return True, None


def bind_scenario_to_pair(
    scenario: Scenario,
    *,
    slug_a: str,
    caps_a: Mapping[str, Any],
    slug_b: str,
    caps_b: Mapping[str, Any],
) -> BindingResult:
    """Pick a role-assignment that satisfies every role's required_capabilities.

    Tries (slug_a→roles[0], slug_b→roles[1]) first, then the swapped form. The
    first assignment that satisfies both roles wins — deterministic and total.
    """
    role_0, role_1 = scenario.agents

    # First permutation.
    ok_a, missing_a = _adapter_satisfies_role(role_0, caps_a)
    ok_b, missing_b = _adapter_satisfies_role(role_1, caps_b)
    if ok_a and ok_b:
        return BindingResult(role_a=role_0.role_key, role_b=role_1.role_key)

    # Swapped permutation.
    ok_a2, missing_a2 = _adapter_satisfies_role(role_1, caps_a)
    ok_b2, missing_b2 = _adapter_satisfies_role(role_0, caps_b)
    if ok_a2 and ok_b2:
        return BindingResult(role_a=role_1.role_key, role_b=role_0.role_key)

    # Neither fit — report the most specific missing capability.
    raise ScenarioBindingError(
        f"No valid binding for scenario {scenario.name!r} on pair ({slug_a}, {slug_b}). "
        f"Direct assignment misses ({slug_a}: {missing_a or '-'}, {slug_b}: {missing_b or '-'}); "
        f"swapped misses ({slug_a}: {missing_a2 or '-'}, {slug_b}: {missing_b2 or '-'})."
    )


def load_adapter_capabilities(slug: str, *, config: Config | None = None) -> dict[str, Any]:
    """Read `<repo_root>/adapters/<slug>/mcp.json` and return its capabilities block."""
    cfg = config or load_config()
    mcp_path: Path = cfg.repo_root / "adapters" / slug / "mcp.json"
    if not mcp_path.exists():
        raise ValueError(f"unknown adapter {slug!r}: no {mcp_path}")
    raw = json.loads(mcp_path.read_text(encoding="utf-8"))
    caps = raw.get("capabilities")
    if not isinstance(caps, dict):
        raise ValueError(f"{mcp_path} has no `capabilities` object")
    return caps


__all__ = [
    "BindingResult",
    "ScenarioBindingError",
    "bind_scenario_to_pair",
    "load_adapter_capabilities",
]
