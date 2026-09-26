"""A victim must never be handed the token its own success criterion watches for.

Found by running, not by reading. Two adversarial scenarios named their success
needle verbatim inside the victim's prompt, in a sentence forbidding it. Both
confirmed the attack against a real agent pair within two seconds, before
either agent had read the shared workspace, because the victim echoed its own
prompt to stdout and the detector matched it.

The deeper problem is validity rather than detection. A victim holding the
token cannot produce evidence that the attacker induced anything: a
confirmation is indistinguishable from the victim repeating its instructions.
These scenarios exist to measure induced behaviour, and a criterion that a
compliant victim can satisfy by reciting its own prompt measures nothing.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

SCENARIO_DIR = pathlib.Path(__file__).resolve().parents[1] / "smadp" / "sandbox" / "scenarios"


def _adversarial_scenarios() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("adversarial"):
            out.append((path.name, data))
    return out


def _needles(data: dict) -> list[str]:
    criteria = data["adversarial"].get("success_criteria") or []
    return [c["needle"] for c in criteria if c.get("needle")]


@pytest.mark.parametrize("name,data", _adversarial_scenarios())
def test_the_victim_is_never_given_the_needle(name: str, data: dict) -> None:
    needles = _needles(data)
    if not needles:
        pytest.skip(f"{name} uses planted assets rather than a literal needle")

    victim_key = data["adversarial"]["victim"]
    victim = (data.get("agents") or {}).get(victim_key) or {}
    text = f"{victim.get('role', '')}\n{victim.get('initial_prompt', '')}"

    leaked = [n for n in needles if n in text]
    assert not leaked, (
        f"{name}: the victim prompt contains {leaked!r}, which its own success "
        f"criterion watches for in the victim's output. Any agent that echoes "
        f"its prompt confirms the attack without acting, and a confirmation "
        f"cannot be distinguished from the victim reciting its instructions. "
        f"Forbid the behaviour without naming the token."
    )


@pytest.mark.parametrize("name,data", _adversarial_scenarios())
def test_the_attacker_may_still_name_the_needle(name: str, data: dict) -> None:
    """The complement, asserted so the fix is not over-applied.

    The attacker has to plant the token, so its prompt naming the needle is
    correct. Stripping it there would leave the scenario unable to stage the
    attack at all, and every run would pass for the wrong reason.
    """
    needles = _needles(data)
    if not needles:
        pytest.skip(f"{name} uses planted assets rather than a literal needle")

    attacker_key = data["adversarial"]["attacker"]
    attacker = (data.get("agents") or {}).get(attacker_key) or {}
    text = f"{attacker.get('role', '')}\n{attacker.get('initial_prompt', '')}"

    assert any(n in text for n in needles), (
        f"{name}: no needle appears in the attacker prompt, so nothing plants "
        f"the token and the victim can never be induced to emit it."
    )


def test_every_needle_is_a_synthetic_secret(name: str = "") -> None:
    """Needles must be synthetic, so a real credential can never become one."""
    for scenario_name, data in _adversarial_scenarios():
        for needle in _needles(data):
            assert needle.startswith(("synthetic-test-only-", "SMADP_TEST_")), (
                f"{scenario_name}: needle {needle!r} is not marked synthetic"
            )
