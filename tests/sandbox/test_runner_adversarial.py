"""Runner: victim-only planted assets + property-first adversarial grading."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from smadp.sandbox.properties import evaluate_properties
from smadp.sandbox.runner import AdapterDescriptor, _build_spec_for_agent, _grade_adversarial
from smadp.sandbox.scenarios import load_scenario
from smadp.sandbox.transcripts import Transcript, TranscriptEvent

TS = datetime(2026, 6, 12, tzinfo=UTC)


def _adapter(slug: str) -> AdapterDescriptor:
    return AdapterDescriptor(
        slug=slug,
        transport="stdio",
        command=("/bin/true",),
        env_required=(),
        image="alpine:3",
        image_digest_pinned="alpine@sha256:" + "0" * 64,
        capabilities={"execute_shell": True},
        trust_floor=0.0,
    )


def _event(agent: str, etype: str, line: str) -> TranscriptEvent:
    return TranscriptEvent(
        agent=agent, direction="agent_to_env", ts=TS, event_type=etype,
        payload={"line": line},
    )


def _transcript(events) -> Transcript:
    return Transcript(run_id="r1", path=Path("/dev/null"), events=list(events))


def test_planted_assets_seeded_into_victim_env_only() -> None:
    sc = load_scenario("secret_exfiltration")
    assert sc.adversarial is not None
    canary_key, canary_val = next(iter(sc.planted_assets.items()))

    victim_spec = _build_spec_for_agent(
        run_id="r1",
        role_key=sc.adversarial.victim,
        role=sc.agent_by_role(sc.adversarial.victim),
        scenario=sc,
        adapter=_adapter("aider"),
        is_victim=True,
    )
    attacker_spec = _build_spec_for_agent(
        run_id="r1",
        role_key=sc.adversarial.attacker,
        role=sc.agent_by_role(sc.adversarial.attacker),
        scenario=sc,
        adapter=_adapter("continue-dev"),
        is_victim=False,
    )

    assert victim_spec.env.get(canary_key) == canary_val
    assert canary_key not in attacker_spec.env


def test_grade_adversarial_fail_when_attack_succeeds() -> None:
    sc = load_scenario("secret_exfiltration")
    canary_val = next(iter(sc.planted_assets.values()))
    tr = _transcript([
        _event("smadp-r1-attacker", "stdout", canary_val),
        _event("smadp-r1-attacker", "exit", "0"),
    ])
    report = evaluate_properties(sc, tr)
    outcome, failures = _grade_adversarial(sc, tr, report)
    assert outcome == "fail"
    assert failures


def test_grade_adversarial_pass_when_defended() -> None:
    sc = load_scenario("secret_exfiltration")
    tr = _transcript([
        _event("smadp-r1-attacker", "stdout", "no secret here"),
        TranscriptEvent(
            agent="smadp-r1-attacker", direction="internal", ts=TS,
            event_type="exit", payload={"code": 0},
        ),
        TranscriptEvent(
            agent="smadp-r1-victim", direction="internal", ts=TS,
            event_type="exit", payload={"code": 0},
        ),
    ])
    report = evaluate_properties(sc, tr)
    outcome, failures = _grade_adversarial(sc, tr, report)
    assert outcome == "pass"
    assert failures == []


def test_grade_adversarial_inconclusive_without_attacker_output() -> None:
    sc = load_scenario("secret_exfiltration")
    tr = _transcript([_event("smadp-r1-victim", "stdout", "hello")])
    report = evaluate_properties(sc, tr)
    outcome, _ = _grade_adversarial(sc, tr, report)
    assert outcome == "inconclusive"
