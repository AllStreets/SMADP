"""Tests for ``smadp.schemas.verdict`` — Verdict + SubVerdicts + Citation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from smadp.schemas.verdict import Citation, SubVerdict, SubVerdicts, Verdict


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data: Any = json.load(fh)
    assert isinstance(data, dict)
    return data


def test_loads_every_seed_verdict(all_verdict_paths: list[Path]) -> None:
    assert len(all_verdict_paths) >= 1
    for path in all_verdict_paths:
        Verdict.model_validate(_load(path))


def test_round_trip(sample_verdict: dict[str, Any]) -> None:
    v = Verdict.model_validate(sample_verdict)
    dumped = v.model_dump(mode="json")
    # Pydantic emits `pair` as list; need to coerce back for tuple validator.
    dumped["pair"] = tuple(dumped["pair"])
    v2 = Verdict.model_validate(dumped)
    assert v2.verdict_id == v.verdict_id


def test_pair_must_be_alphabetized(sample_verdict: dict[str, Any]) -> None:
    payload = deepcopy(sample_verdict)
    payload["pair"] = list(reversed(payload["pair"]))
    with pytest.raises(ValidationError):
        Verdict.model_validate(payload)


def test_pair_cannot_be_same(sample_verdict: dict[str, Any]) -> None:
    payload = deepcopy(sample_verdict)
    payload["pair"] = [payload["pair"][0], payload["pair"][0]]
    with pytest.raises(ValidationError):
        Verdict.model_validate(payload)


def test_extra_fields_rejected(sample_verdict: dict[str, Any]) -> None:
    payload = deepcopy(sample_verdict)
    payload["future_field"] = 1
    with pytest.raises(ValidationError):
        Verdict.model_validate(payload)


def test_stale_reason_defaults_none(sample_verdict: dict[str, Any]) -> None:
    v = Verdict.model_validate(deepcopy(sample_verdict))
    assert v.stale_reason is None


def test_stale_reason_accepts_capability_drift(sample_verdict: dict[str, Any]) -> None:
    payload = deepcopy(sample_verdict)
    payload["stale_reason"] = "capability_drift"
    v = Verdict.model_validate(payload)
    assert v.stale_reason == "capability_drift"


def test_stale_reason_rejects_unknown(sample_verdict: dict[str, Any]) -> None:
    payload = deepcopy(sample_verdict)
    payload["stale_reason"] = "bogus"
    with pytest.raises(ValidationError):
        Verdict.model_validate(payload)


def test_composite_score_bounds(sample_verdict: dict[str, Any]) -> None:
    for bad in (-0.01, 1.01, 2.0):
        payload = deepcopy(sample_verdict)
        payload["composite_score"] = bad
        with pytest.raises(ValidationError):
            Verdict.model_validate(payload)


def test_invalid_verdict_id_rejected(sample_verdict: dict[str, Any]) -> None:
    payload = deepcopy(sample_verdict)
    payload["verdict_id"] = "not-a-valid-id"
    with pytest.raises(ValidationError):
        Verdict.model_validate(payload)


# ----------------------------------------------------- participants (N-ary)
class TestParticipants:
    """Verdict schema: N-ary participants generalization."""

    def test_legacy_pair_only_derives_participants(self, sample_verdict: dict[str, Any]) -> None:
        # Legacy seed verdict files have `pair` but no `participants`.
        payload = deepcopy(sample_verdict)
        payload.pop("participants", None)
        v = Verdict.model_validate(payload)
        assert v.participants == list(v.pair)  # type: ignore[arg-type]
        assert len(v.participants) == 2

    def test_participants_only_derives_legacy_pair(self, sample_verdict: dict[str, Any]) -> None:
        # New-style payload: only participants, no pair.
        payload = deepcopy(sample_verdict)
        a, b = payload["pair"]
        payload["participants"] = [a, b]
        del payload["pair"]
        v = Verdict.model_validate(payload)
        assert v.participants == [a, b]
        assert tuple(v.pair) == (a, b)  # type: ignore[arg-type]

    def test_accepts_three_participants(self, sample_verdict: dict[str, Any]) -> None:
        payload = deepcopy(sample_verdict)
        payload["participants"] = ["aider", "autogen", "continue-dev"]
        del payload["pair"]
        v = Verdict.model_validate(payload)
        assert v.participants == ["aider", "autogen", "continue-dev"]
        assert v.pair is None  # N>=3 has no legacy pair

    def test_accepts_four_participants(self, sample_verdict: dict[str, Any]) -> None:
        payload = deepcopy(sample_verdict)
        payload["participants"] = ["aa", "bb", "cc", "dd"]
        del payload["pair"]
        v = Verdict.model_validate(payload)
        assert v.participants == ["aa", "bb", "cc", "dd"]
        assert v.pair is None

    def test_rejects_five_participants(self, sample_verdict: dict[str, Any]) -> None:
        payload = deepcopy(sample_verdict)
        payload["participants"] = ["aa", "bb", "cc", "dd", "ee"]
        del payload["pair"]
        with pytest.raises(ValidationError):
            Verdict.model_validate(payload)

    def test_rejects_one_participant(self, sample_verdict: dict[str, Any]) -> None:
        payload = deepcopy(sample_verdict)
        payload["participants"] = ["solo-agent"]
        del payload["pair"]
        with pytest.raises(ValidationError):
            Verdict.model_validate(payload)

    def test_rejects_unalphabetized_participants(self, sample_verdict: dict[str, Any]) -> None:
        payload = deepcopy(sample_verdict)
        payload["participants"] = ["zebra", "aardvark", "moose"]
        del payload["pair"]
        with pytest.raises(ValidationError):
            Verdict.model_validate(payload)

    def test_rejects_duplicate_participants(self, sample_verdict: dict[str, Any]) -> None:
        payload = deepcopy(sample_verdict)
        payload["participants"] = ["aider", "aider", "cursor"]
        del payload["pair"]
        with pytest.raises(ValidationError):
            Verdict.model_validate(payload)

    def test_rejects_pair_set_for_n_ary(self, sample_verdict: dict[str, Any]) -> None:
        # If a caller sets pair for a 3-agent verdict, that's a bug.
        payload = deepcopy(sample_verdict)
        payload["participants"] = ["aa", "bb", "cc"]
        payload["pair"] = ["aa", "bb"]
        with pytest.raises(ValidationError):
            Verdict.model_validate(payload)

    def test_pair_disagrees_with_participants_raises(self, sample_verdict: dict[str, Any]) -> None:
        payload = deepcopy(sample_verdict)
        payload["pair"] = ["aa", "bb"]
        payload["participants"] = ["xx", "yy"]
        with pytest.raises(ValidationError):
            Verdict.model_validate(payload)

    def test_neither_pair_nor_participants_raises(self, sample_verdict: dict[str, Any]) -> None:
        payload = deepcopy(sample_verdict)
        payload.pop("pair", None)
        payload.pop("participants", None)
        with pytest.raises(ValidationError):
            Verdict.model_validate(payload)


# ----------------------------------------------------------- SubVerdicts model
class TestSubVerdicts:
    @staticmethod
    def _stub() -> SubVerdict:
        return SubVerdict(
            severity="low",
            rationale="placeholder rationale that is non-empty",
            citations=[Citation(profile_field="agent_a.capabilities.execute_shell")],
        )

    def test_requires_all_five_keys(self) -> None:
        # Missing E_compliance.
        with pytest.raises(ValidationError):
            SubVerdicts.model_validate(
                {
                    "A_prompt_injection": self._stub().model_dump(),
                    "B_data_leakage": self._stub().model_dump(),
                    "C_capability_conflict": self._stub().model_dump(),
                    "D_cascading_error": self._stub().model_dump(),
                }
            )

    def test_accepts_all_five(self) -> None:
        SubVerdicts(
            A_prompt_injection=self._stub(),
            B_data_leakage=self._stub(),
            C_capability_conflict=self._stub(),
            D_cascading_error=self._stub(),
            E_compliance=self._stub(),
        )

    def test_extra_risk_key_rejected(self) -> None:
        payload = {
            name: self._stub().model_dump()
            for name in (
                "A_prompt_injection",
                "B_data_leakage",
                "C_capability_conflict",
                "D_cascading_error",
                "E_compliance",
            )
        }
        payload["F_made_up"] = self._stub().model_dump()
        with pytest.raises(ValidationError):
            SubVerdicts.model_validate(payload)


# ------------------------------------------------------------- Citation model
class TestCitation:
    def test_at_least_one_field_required(self) -> None:
        with pytest.raises(ValidationError):
            Citation()

    def test_blank_fields_count_as_missing(self) -> None:
        # Empty strings are falsy; the validator's ``not`` check should reject.
        with pytest.raises(ValidationError):
            Citation(profile_field="", evidence_ref=None, quote="")

    def test_profile_field_alone_ok(self) -> None:
        c = Citation(profile_field="agent_a.capabilities.execute_shell")
        assert c.profile_field == "agent_a.capabilities.execute_shell"

    def test_evidence_ref_alone_ok(self) -> None:
        good = "sha256:" + "0" * 64
        c = Citation(evidence_ref=good)
        assert c.evidence_ref == good

    def test_quote_alone_ok(self) -> None:
        c = Citation(quote="this is a verbatim quote from the docs")
        assert c.quote.startswith("this")

    def test_invalid_evidence_ref_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Citation(evidence_ref="sha256:bad")
