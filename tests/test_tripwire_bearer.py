"""The planted value has a legitimate holder, and scanning it halts the scenario.

planted_assets serves two opposite purposes. In secret_exfiltration the value
is a canary in the victim's environment and the finding is the attacker
obtaining it. In induced_execution, state_poisoning and partner_escalation the
value is a payload the attacker must plant and the finding is the victim
reproducing it.

Treating those alike halted three of four scenarios the first time they ran
against real agents, at the moment the attacker wrote the file it was told to
write, before the victim had read anything.
"""
from __future__ import annotations

import pytest

from smadp.sandbox.scenarios import load_scenario
from smadp.sandbox.tripwire import TranscriptEvent, check_event, context_for_scenario


def _event(agent: str, line: str) -> TranscriptEvent:
    return TranscriptEvent(ts="2026-09-26T00:00:00Z", agent=agent,
                           event_type="stdout", direction="internal",
                           payload={"line": line})


def _planted(scenario_name: str) -> tuple[object, str]:
    s = load_scenario(scenario_name)
    values = [v for v in {**s.synthetic_secrets, **s.planted_assets}.values() if v]
    assert values, f"{scenario_name} plants nothing"
    return s, values[0]


@pytest.mark.parametrize(
    "scenario_name", ["induced_execution", "state_poisoning", "partner_escalation"])
def test_the_attacker_may_plant_without_tripping(scenario_name: str) -> None:
    """These scenarios confirm on the victim's output, so the attacker emitting
    the payload is the scenario working."""
    scenario, value = _planted(scenario_name)
    ctx = context_for_scenario(scenario)
    assert ctx.secret_bearing_role == scenario.adversarial.attacker

    hit = check_event(_event(f"smadp-run-{scenario.adversarial.attacker}", value), ctx)
    assert hit is None, (
        f"{scenario_name}: the attacker tripped the wire for planting its own "
        f"payload, which halts the run before the victim can act")


@pytest.mark.parametrize(
    "scenario_name", ["induced_execution", "state_poisoning", "partner_escalation"])
def test_the_victim_emitting_it_still_trips(scenario_name: str) -> None:
    """The exemption must not disarm the rule: the victim reproducing the
    payload is exactly the finding these scenarios exist to catch."""
    scenario, value = _planted(scenario_name)
    ctx = context_for_scenario(scenario)

    hit = check_event(_event(f"smadp-run-{scenario.adversarial.victim}", value), ctx)
    assert hit is not None and hit.rule == "planted_secret_in_output"


def test_exfiltration_reverses_the_roles() -> None:
    """The canary lives in the victim's environment there, so the victim holds
    it legitimately and the attacker holding it is the finding."""
    scenario, value = _planted("secret_exfiltration")
    ctx = context_for_scenario(scenario)
    assert ctx.secret_bearing_role == scenario.adversarial.victim

    assert check_event(_event("smadp-run-victim", value), ctx) is None
    hit = check_event(_event("smadp-run-attacker", value), ctx)
    assert hit is not None and hit.rule == "planted_secret_in_output"


def test_a_cooperative_scenario_exempts_nobody() -> None:
    """With no adversarial roles there is no legitimate holder, so every agent
    is scanned, which is the stricter and correct default."""
    scenario = load_scenario("calendar_email")
    ctx = context_for_scenario(scenario)
    assert ctx.secret_bearing_role == ""
