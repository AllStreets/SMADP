"""Loader accepts scenarios with 2, 3, or 4 named agents."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.sandbox.scenarios.loader import (
    ScenarioLoadError,
    load_scenario_from_path,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / f"{name}.yaml"
    p.write_text(body, encoding="utf-8")
    return p


_HEADER = """\
name: {name}
description: A test scenario.
timeout_s: 60
shared_workspace:
  type: tmpfs
  files: [/work/scratchpad.md]
allow_egress: []
synthetic_secrets: []
assertions:
  - type: both_agents_exited_zero
"""


def _agent_block(role: str, caps: list[str]) -> str:
    caps_yaml = ", ".join(caps)
    return f"""\
  {role}:
    adapter: null
    required_capabilities: [{caps_yaml}]
    role: "Plays the {role} role."
    initial_prompt: "Do the {role} task."
"""


def test_loader_accepts_two_agents(tmp_path: Path) -> None:
    body = _HEADER.format(name="two_agent") + "agents:\n"
    body += _agent_block("planner", ["read_filesystem"])
    body += _agent_block("executor", ["read_filesystem", "write_filesystem"])
    path = _write(tmp_path, "two_agent", body)

    scenario = load_scenario_from_path(path)

    assert len(scenario.agents) == 2
    assert tuple(a.role_key for a in scenario.agents) == ("planner", "executor")


def test_loader_accepts_three_agents(tmp_path: Path) -> None:
    body = _HEADER.format(name="three_agent") + "agents:\n"
    body += _agent_block("planner", ["read_filesystem"])
    body += _agent_block("executor", ["read_filesystem", "write_filesystem"])
    body += _agent_block("reviewer", ["read_filesystem"])
    path = _write(tmp_path, "three_agent", body)

    scenario = load_scenario_from_path(path)

    assert len(scenario.agents) == 3
    assert tuple(a.role_key for a in scenario.agents) == (
        "planner",
        "executor",
        "reviewer",
    )


def test_loader_accepts_four_agents(tmp_path: Path) -> None:
    body = _HEADER.format(name="four_agent") + "agents:\n"
    body += _agent_block("a", ["read_filesystem"])
    body += _agent_block("b", ["read_filesystem"])
    body += _agent_block("c", ["read_filesystem"])
    body += _agent_block("d", ["read_filesystem"])
    path = _write(tmp_path, "four_agent", body)

    scenario = load_scenario_from_path(path)

    assert len(scenario.agents) == 4
    assert tuple(a.role_key for a in scenario.agents) == ("a", "b", "c", "d")


def test_loader_rejects_one_agent(tmp_path: Path) -> None:
    body = _HEADER.format(name="one_agent") + "agents:\n"
    body += _agent_block("solo", ["read_filesystem"])
    path = _write(tmp_path, "one_agent", body)

    with pytest.raises(ScenarioLoadError, match=r"2 to 4"):
        load_scenario_from_path(path)


def test_loader_rejects_five_agents(tmp_path: Path) -> None:
    body = _HEADER.format(name="five_agent") + "agents:\n"
    for role in ("a", "b", "c", "d", "e"):
        body += _agent_block(role, ["read_filesystem"])
    path = _write(tmp_path, "five_agent", body)

    with pytest.raises(ScenarioLoadError, match=r"2 to 4"):
        load_scenario_from_path(path)
