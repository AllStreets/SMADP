"""Scenario definitions and loader for the Sandbox Validator.

A scenario is a YAML file that describes:

* the two agent roles (``calendar`` / ``email``, etc.) and their initial
  prompts;
* shared resources (only filesystem dirs and inference endpoints by default);
* synthetic secrets to inject (must pass ``policy.is_safe_secret``);
* an outbound egress allow-list (often empty);
* a success rubric — a list of typed assertions that the runner evaluates
  against the transcript to decide ``pass`` / ``fail`` / ``inconclusive``.

See :mod:`smadp.sandbox.scenarios.loader` for the canonical schema.
"""

from __future__ import annotations

from smadp.sandbox.scenarios.loader import (
    ADVERSARIAL_OBJECTIVES,
    SUPPORTED_SUCCESS_CRITERIA,
    AdversarialSpec,
    AgentRole,
    Assertion,
    Scenario,
    ScenarioLoadError,
    SuccessCriterion,
    list_builtin_scenarios,
    load_scenario,
    load_scenario_from_path,
    scenario_mode,
)

__all__ = [
    "ADVERSARIAL_OBJECTIVES",
    "SUPPORTED_SUCCESS_CRITERIA",
    "AdversarialSpec",
    "AgentRole",
    "Assertion",
    "Scenario",
    "ScenarioLoadError",
    "SuccessCriterion",
    "list_builtin_scenarios",
    "load_scenario",
    "load_scenario_from_path",
    "scenario_mode",
]
