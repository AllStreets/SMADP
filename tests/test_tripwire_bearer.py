"""The planted value has a legitimate holder, and scanning it halts the scenario.

planted_assets exists for one purpose after the criterion redesign: a canary
in the victim's environment whose appearance in the attacker's output is the
finding, as in secret_exfiltration. The three scenarios that confirm on the
victim acting now use a file criterion and plant no value at all, because a
value the victim must read is a value the victim will display, and displaying
untrusted content is not the behaviour those scenarios measure.
"""
from __future__ import annotations

import pytest

from smadp.sandbox.scenarios import load_scenario
from smadp.sandbox.tripwire import TranscriptEvent, check_event, context_for_scenario


def _event(agent: str, line: str) -> TranscriptEvent:
    return TranscriptEvent(ts="2026-09-26T00:00:00Z", agent=agent,
                           event_type="stdout", direction="internal",
                           payload={"line": line})


def test_exfiltration_reverses_the_roles() -> None:
    """The canary lives in the victim's environment, so the victim holds it
    legitimately and the attacker holding it is the finding."""
    scenario = load_scenario("secret_exfiltration")
    value = next(v for v in scenario.planted_assets.values() if v)
    ctx = context_for_scenario(scenario)
    assert ctx.secret_bearing_role == scenario.adversarial.victim

    assert check_event(_event("smadp-run-victim", value), ctx) is None
    hit = check_event(_event("smadp-run-attacker", value), ctx)
    assert hit is not None and hit.rule == "planted_secret_in_output"


@pytest.mark.parametrize(
    "scenario_name", ["induced_execution", "state_poisoning", "partner_escalation"])
def test_file_criterion_scenarios_give_the_wire_nothing_to_match(scenario_name: str) -> None:
    """Their finding is a file the victim creates. There is no planted value,
    so a victim that displays the planted file cannot be halted for it, and
    the bearer role is still derived so a future value would exempt the right
    side."""
    scenario = load_scenario(scenario_name)
    ctx = context_for_scenario(scenario)
    assert ctx.secret_values == ()
    assert ctx.secret_bearing_role == scenario.adversarial.attacker


def test_a_cooperative_scenario_exempts_nobody() -> None:
    scenario = load_scenario("calendar_email")
    assert context_for_scenario(scenario).secret_bearing_role == ""
