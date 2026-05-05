"""Capability-based scenario↔adapter binding."""

from __future__ import annotations

from typing import Any

import pytest

from smadp.sandbox.binding import (
    BindingResult,
    ScenarioBindingError,
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
    assert result == BindingResult(role_a="role_a", role_b="role_b")


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
    assert result == BindingResult(role_a="role_b", role_b="role_a")


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
    assert result.role_a == "role_a"


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
