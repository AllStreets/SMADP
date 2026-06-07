"""Decide which scenario role each adapter plays (N-ary; N in 2..4)."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from smadp.config import Config, load_config
from smadp.sandbox.scenarios.loader import AgentRole, Scenario


class ScenarioBindingError(RuntimeError):
    """Raised when no assignment of (slug → role) satisfies the scenario."""


@dataclass(frozen=True)
class BindingResult:
    """A mapping from role_key → adapter slug. The mapping is read-only."""

    role_to_slug: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.role_to_slug, MappingProxyType):
            # Freeze the underlying dict via a read-only proxy.
            object.__setattr__(self, "role_to_slug", MappingProxyType(dict(self.role_to_slug)))


def _adapter_satisfies_role(role: AgentRole, caps: Mapping[str, Any]) -> tuple[bool, str | None]:
    for cap in role.required_capabilities:
        value = caps.get(cap)
        if cap == "network_egress":
            if value is None or value == "none":
                return False, cap
        else:
            if not bool(value):
                return False, cap
    return True, None


def bind_scenario(
    scenario: Scenario,
    *,
    agents: Mapping[str, Mapping[str, Any]],
) -> BindingResult:
    """Find an assignment of (role_key → slug) that satisfies every role.

    Tries every permutation of len(scenario.agents) slugs across the role keys
    (in scenario-declared order). The first assignment whose required
    capabilities are all satisfied wins. Deterministic: insertion order of
    ``agents`` defines the tiebreak.

    Diagnostics:
        On failure, the error reports the missing capabilities from the last
        permutation tried (arbitrary among unsatisfiable permutations). This
        is a sample for debugging, not a "closest fit" report.
    """
    role_order = tuple(role.role_key for role in scenario.agents)
    roles_by_key = {role.role_key: role for role in scenario.agents}
    slugs = list(agents.keys())

    if len(slugs) < len(scenario.agents):
        raise ScenarioBindingError(
            f"Scenario {scenario.name!r} needs {len(scenario.agents)} agents; "
            f"only {len(slugs)} candidate(s) provided"
        )

    last_miss: list[str] = []
    for perm in itertools.permutations(slugs, len(scenario.agents)):
        mapping = dict(zip(role_order, perm, strict=True))
        ok = True
        miss: list[str] = []
        for role_key, slug in mapping.items():
            role = roles_by_key[role_key]
            satisfied, missing = _adapter_satisfies_role(role, agents[slug])
            if not satisfied:
                ok = False
                miss.append(f"{slug}→{role_key}:{missing}")
        if ok:
            return BindingResult(role_to_slug=mapping)
        last_miss = miss

    raise ScenarioBindingError(
        f"No valid binding for scenario {scenario.name!r} on candidates "
        f"{slugs}. Sample miss (from last permutation tried; diagnostic only): "
        f"{last_miss}"
    )


# ---- Legacy length-2 alias (delete after one release cycle) ---------------


@dataclass(frozen=True)
class _LegacyBindingResult:
    role_a: str
    role_b: str


def bind_scenario_to_pair(
    scenario: Scenario,
    *,
    slug_a: str,
    caps_a: Mapping[str, Any],
    slug_b: str,
    caps_b: Mapping[str, Any],
) -> _LegacyBindingResult:
    """Length-2 shim that delegates to bind_scenario.

    Returns role_a (the role bound to slug_a) and role_b (bound to slug_b).
    """
    result = bind_scenario(scenario, agents={slug_a: caps_a, slug_b: caps_b})
    inverse = {slug: role for role, slug in result.role_to_slug.items()}
    return _LegacyBindingResult(
        role_a=inverse[slug_a],
        role_b=inverse[slug_b],
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
    "bind_scenario",
    "bind_scenario_to_pair",
    "load_adapter_capabilities",
]
