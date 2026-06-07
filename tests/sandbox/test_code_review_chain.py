"""Smoke: the new 3-agent scenario parses and binds against existing adapters."""

from __future__ import annotations

from pathlib import Path

from smadp.sandbox.binding import bind_scenario, load_adapter_capabilities
from smadp.sandbox.scenarios.loader import load_scenario


def test_code_review_chain_loads() -> None:
    scenario = load_scenario("code_review_chain")
    assert scenario.name == "code_review_chain"
    assert len(scenario.agents) == 3
    role_keys = tuple(a.role_key for a in scenario.agents)
    assert role_keys == ("planner", "executor", "reviewer")


def test_code_review_chain_binds_against_real_adapters(tmp_path: Path) -> None:
    """The four real adapter mcp.json capability blocks must cover this chain.

    Picks 3 of the 4 existing adapters (aider, autogen, continue-dev) and
    confirms the binder finds an assignment.
    """
    scenario = load_scenario("code_review_chain")
    agents = {
        slug: load_adapter_capabilities(slug) for slug in ("aider", "autogen", "continue-dev")
    }
    result = bind_scenario(scenario, agents=agents)
    # Pins the deterministic-tiebreak contract in bind_scenario's docstring:
    # "Deterministic: insertion order of `agents` defines the tiebreak."
    # All three adapters satisfy the requested caps, so the first permutation
    # wins and the mapping is the insertion order of `agents` against the
    # scenario-declared role order.
    assert dict(result.role_to_slug) == {
        "planner": "aider",
        "executor": "autogen",
        "reviewer": "continue-dev",
    }
