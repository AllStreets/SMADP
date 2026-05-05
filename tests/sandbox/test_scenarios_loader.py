"""Scenario loader — required_capabilities support."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from smadp.sandbox.scenarios import load_scenario, load_scenario_from_path
from smadp.sandbox.scenarios.loader import ScenarioLoadError


def test_loaded_scenarios_expose_required_capabilities() -> None:
    for name in ("calendar_email", "coding_browser", "notes_email", "spreadsheet_powerpoint"):
        scenario = load_scenario(name)
        for role in scenario.agents:
            assert isinstance(role.required_capabilities, tuple)
            assert all(isinstance(c, str) and c for c in role.required_capabilities)
            assert len(role.required_capabilities) >= 1, (
                f"{name}.{role.role_key} must declare at least one capability"
            )


def test_unknown_capability_rejected(tmp_path: Path) -> None:
    bad = {
        "name": "bad_scenario",
        "description": "nope",
        "timeout_s": 60,
        "agents": {
            "a": {
                "required_capabilities": ["execute_shell", "fly_to_the_moon"],
                "role": "x",
                "initial_prompt": "x",
            },
            "b": {
                "required_capabilities": ["execute_shell"],
                "role": "y",
                "initial_prompt": "y",
            },
        },
        "shared_workspace": {"type": "tmpfs", "files": []},
        "allow_egress": [],
        "synthetic_secrets": [],
        "assertions": [{"type": "both_agents_exited_zero"}],
    }
    p = tmp_path / "bad_scenario.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match="unknown capability"):
        load_scenario_from_path(p)


def test_empty_required_capabilities_rejected(tmp_path: Path) -> None:
    bad = {
        "name": "bad_scenario",
        "description": "nope",
        "timeout_s": 60,
        "agents": {
            "a": {"required_capabilities": [], "role": "x", "initial_prompt": "x"},
            "b": {"required_capabilities": ["execute_shell"], "role": "y", "initial_prompt": "y"},
        },
        "shared_workspace": {"type": "tmpfs", "files": []},
        "allow_egress": [],
        "synthetic_secrets": [],
        "assertions": [{"type": "both_agents_exited_zero"}],
    }
    p = tmp_path / "bad_scenario.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match="non-empty list"):
        load_scenario_from_path(p)


def test_duplicate_capabilities_rejected(tmp_path: Path) -> None:
    bad = {
        "name": "bad_scenario",
        "description": "nope",
        "timeout_s": 60,
        "agents": {
            "a": {
                "required_capabilities": ["execute_shell", "execute_shell"],
                "role": "x",
                "initial_prompt": "x",
            },
            "b": {"required_capabilities": ["execute_shell"], "role": "y", "initial_prompt": "y"},
        },
        "shared_workspace": {"type": "tmpfs", "files": []},
        "allow_egress": [],
        "synthetic_secrets": [],
        "assertions": [{"type": "both_agents_exited_zero"}],
    }
    p = tmp_path / "bad_scenario.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match="duplicate values"):
        load_scenario_from_path(p)
