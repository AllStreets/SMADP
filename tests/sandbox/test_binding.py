"""Capability-based scenario↔adapter binding."""

from __future__ import annotations

from typing import Any

import pytest

from smadp.sandbox.binding import (
    ScenarioBindingError,
    _LegacyBindingResult,
    bind_scenario_to_pair,
)
from smadp.sandbox.scenarios.loader import AgentRole, Assertion, Scenario


def _scenario(*, cap_a: tuple[str, ...], cap_b: tuple[str, ...]) -> Scenario:
    return Scenario(
        name="test_scenario",
        description="x",
        timeout_s=60,
        agents=(
            AgentRole(
                role_key="role_a",
                adapter=None,
                role="x",
                initial_prompt="x",
                required_capabilities=cap_a,
            ),
            AgentRole(
                role_key="role_b",
                adapter=None,
                role="y",
                initial_prompt="y",
                required_capabilities=cap_b,
            ),
        ),
        shared_workspace_files=(),
        allow_egress=(),
        synthetic_secrets={},
        assertions=(Assertion(type="both_agents_exited_zero"),),
    )


def _caps(**flags: bool | str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "execute_shell": False,
        "read_filesystem": False,
        "write_filesystem": False,
        "network_egress": "none",
        "spawn_subprocesses": False,
        "use_mcp": False,
        "modify_git_state": False,
        "install_packages": False,
        "run_browsers": False,
    }
    base.update(flags)
    return base


def test_first_assignment_fits() -> None:
    sc = _scenario(cap_a=("execute_shell",), cap_b=("read_filesystem",))
    aider_caps = _caps(execute_shell=True)
    cont_caps = _caps(read_filesystem=True)
    result = bind_scenario_to_pair(
        sc,
        slug_a="aider",
        caps_a=aider_caps,
        slug_b="continue-dev",
        caps_b=cont_caps,
    )
    assert result == _LegacyBindingResult(role_a="role_a", role_b="role_b")


def test_second_assignment_fits_when_first_does_not() -> None:
    sc = _scenario(cap_a=("read_filesystem",), cap_b=("execute_shell",))
    aider_caps = _caps(execute_shell=True)
    cont_caps = _caps(read_filesystem=True)
    # aider can satisfy role_b (execute_shell); continue-dev satisfies role_a.
    result = bind_scenario_to_pair(
        sc,
        slug_a="aider",
        caps_a=aider_caps,
        slug_b="continue-dev",
        caps_b=cont_caps,
    )
    assert result == _LegacyBindingResult(role_a="role_b", role_b="role_a")


def test_neither_assignment_fits_raises() -> None:
    sc = _scenario(cap_a=("run_browsers",), cap_b=("execute_shell",))
    aider_caps = _caps(execute_shell=True)
    cont_caps = _caps(execute_shell=True)
    with pytest.raises(ScenarioBindingError, match="run_browsers"):
        bind_scenario_to_pair(
            sc,
            slug_a="aider",
            caps_a=aider_caps,
            slug_b="continue-dev",
            caps_b=cont_caps,
        )


def test_network_egress_satisfied_by_any_non_none() -> None:
    sc = _scenario(cap_a=("network_egress",), cap_b=("execute_shell",))
    aider_caps = _caps(network_egress="broad")
    cont_caps = _caps(execute_shell=True)
    result = bind_scenario_to_pair(
        sc,
        slug_a="aider",
        caps_a=aider_caps,
        slug_b="continue-dev",
        caps_b=cont_caps,
    )
    assert result == _LegacyBindingResult(role_a="role_a", role_b="role_b")


def test_network_egress_not_satisfied_by_none() -> None:
    sc = _scenario(cap_a=("network_egress",), cap_b=("execute_shell",))
    aider_caps = _caps(network_egress="none")
    cont_caps = _caps(execute_shell=True)
    with pytest.raises(ScenarioBindingError, match="network_egress"):
        bind_scenario_to_pair(
            sc,
            slug_a="aider",
            caps_a=aider_caps,
            slug_b="continue-dev",
            caps_b=cont_caps,
        )


def test_missing_cap_key_treated_as_absent() -> None:
    """If an adapter's caps dict doesn't include a required key, binding fails."""
    sc = _scenario(cap_a=("run_browsers",), cap_b=("execute_shell",))
    # caps_a omits run_browsers entirely (real adapters set it false; this is the absent case)
    caps_a_no_browser: dict[str, Any] = {
        k: v for k, v in _caps(execute_shell=True).items() if k != "run_browsers"
    }
    caps_b_no_browser: dict[str, Any] = {
        k: v for k, v in _caps(execute_shell=True).items() if k != "run_browsers"
    }
    with pytest.raises(ScenarioBindingError, match="run_browsers"):
        bind_scenario_to_pair(
            sc,
            slug_a="aider",
            caps_a=caps_a_no_browser,
            slug_b="continue-dev",
            caps_b=caps_b_no_browser,
        )


def test_symmetric_scenario_returns_direct_assignment() -> None:
    """When both permutations satisfy the scenario, direct assignment wins (deterministic)."""
    sc = _scenario(cap_a=("execute_shell",), cap_b=("read_filesystem",))
    caps_both = _caps(execute_shell=True, read_filesystem=True)
    result = bind_scenario_to_pair(
        sc,
        slug_a="aider",
        caps_a=caps_both,
        slug_b="continue-dev",
        caps_b=caps_both,
    )
    assert result == _LegacyBindingResult(role_a="role_a", role_b="role_b")


# --- N-ary binder tests --------------------------------------------------

from smadp.sandbox.binding import bind_scenario


def _role(key: str, caps: tuple[str, ...]) -> AgentRole:
    return AgentRole(
        role_key=key,
        adapter=None,
        role=f"{key} role",
        initial_prompt=f"{key} prompt",
        required_capabilities=caps,
    )


def _scenario_nary(*roles: AgentRole) -> Scenario:
    return Scenario(
        name="test",
        description="d",
        timeout_s=60,
        agents=roles,
        shared_workspace_files=(),
        allow_egress=(),
        synthetic_secrets={},
        assertions=(),
    )


def test_bind_scenario_length_three_satisfies_all_roles() -> None:
    scn = _scenario_nary(
        _role("planner", ("read_filesystem",)),
        _role("executor", ("read_filesystem", "write_filesystem")),
        _role("reviewer", ("read_filesystem",)),
    )
    agents = {
        "alice": {"read_filesystem": True, "write_filesystem": False},
        "bob":   {"read_filesystem": True, "write_filesystem": True},
        "carol": {"read_filesystem": True, "write_filesystem": False},
    }

    result = bind_scenario(scn, agents=agents)

    # "bob" is the only adapter with write_filesystem, so it must be executor.
    assert result.role_to_slug["executor"] == "bob"
    assert set(result.role_to_slug.keys()) == {"planner", "executor", "reviewer"}
    assert set(result.role_to_slug.values()) == {"alice", "bob", "carol"}


def test_bind_scenario_length_four_satisfies_all_roles() -> None:
    scn = _scenario_nary(
        _role("a", ("read_filesystem",)),
        _role("b", ("write_filesystem",)),
        _role("c", ("execute_shell",)),
        _role("d", ("modify_git_state",)),
    )
    agents = {
        "p": {"read_filesystem": True},
        "q": {"write_filesystem": True},
        "r": {"execute_shell": True},
        "s": {"modify_git_state": True},
    }

    result = bind_scenario(scn, agents=agents)

    assert result.role_to_slug == {"a": "p", "b": "q", "c": "r", "d": "s"}


def test_bind_scenario_raises_when_no_permutation_fits() -> None:
    scn = _scenario_nary(
        _role("planner", ("read_filesystem",)),
        _role("executor", ("write_filesystem",)),
        _role("reviewer", ("modify_git_state",)),
    )
    agents = {
        "alice": {"read_filesystem": True},
        "bob":   {"read_filesystem": True, "write_filesystem": True},
        "carol": {"read_filesystem": True},   # no modify_git_state anywhere
    }

    with pytest.raises(ScenarioBindingError, match="No valid binding"):
        bind_scenario(scn, agents=agents)


def test_bind_scenario_length_two_matches_legacy_behavior() -> None:
    scn = _scenario_nary(
        _role("calendar", ("execute_shell", "write_filesystem")),
        _role("email", ("execute_shell", "read_filesystem")),
    )
    agents = {
        "writer": {"execute_shell": True, "write_filesystem": True},
        "reader": {"execute_shell": True, "read_filesystem": True},
    }

    result = bind_scenario(scn, agents=agents)

    assert result.role_to_slug == {"calendar": "writer", "email": "reader"}
