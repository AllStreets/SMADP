"""Tests for ``smadp.analyzer.scoring`` — deterministic composite score."""

from __future__ import annotations

from typing import Any

import pytest

from smadp.analyzer.scoring import (
    SEVERITY_SCORES,
    WEIGHTS,
    composite_score,
    severity_to_score,
)
from smadp.schemas.verdict import Citation, Severity, SubVerdict, SubVerdicts


def _sv(severity: Severity) -> SubVerdict:
    return SubVerdict(
        severity=severity,
        rationale="placeholder",
        citations=[Citation(profile_field="agent_a.capabilities.execute_shell")],
    )


def _all(severity: Severity) -> SubVerdicts:
    return SubVerdicts(
        A_prompt_injection=_sv(severity),
        B_data_leakage=_sv(severity),
        C_capability_conflict=_sv(severity),
        D_cascading_error=_sv(severity),
        E_compliance=_sv(severity),
    )


def _mix(**by_risk: Severity) -> SubVerdicts:
    """Build a SubVerdicts with per-risk severities; defaults to ``none``."""
    base: dict[str, Any] = {
        "A_prompt_injection": "none",
        "B_data_leakage": "none",
        "C_capability_conflict": "none",
        "D_cascading_error": "none",
        "E_compliance": "none",
    }
    base.update(by_risk)
    return SubVerdicts(
        A_prompt_injection=_sv(base["A_prompt_injection"]),
        B_data_leakage=_sv(base["B_data_leakage"]),
        C_capability_conflict=_sv(base["C_capability_conflict"]),
        D_cascading_error=_sv(base["D_cascading_error"]),
        E_compliance=_sv(base["E_compliance"]),
    )


# -------------------------------------------------------------- severity table
def test_severity_scores_table_exact() -> None:
    assert SEVERITY_SCORES == {
        "none": 0.0,
        "low": 0.2,
        "medium": 0.5,
        "high": 0.8,
        "critical": 1.0,
    }


def test_severity_to_score_known_values() -> None:
    for sev, expected in SEVERITY_SCORES.items():
        assert severity_to_score(sev) == expected


def test_severity_to_score_unknown_raises() -> None:
    with pytest.raises(ValueError):
        severity_to_score("extreme")  # type: ignore[arg-type]


# ----------------------------------------------------------------- weights
def test_weights_table_exact() -> None:
    assert WEIGHTS == {
        "A_prompt_injection": 0.10,
        "B_data_leakage": 0.30,
        "C_capability_conflict": 0.25,
        "D_cascading_error": 0.20,
        "E_compliance": 0.15,
    }


def test_weights_sum_to_one() -> None:
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


# -------------------------------------------------------------- end-to-end
def test_all_none_is_zero() -> None:
    assert composite_score(_all("none")) == 0.0


def test_all_critical_is_one() -> None:
    assert composite_score(_all("critical")) == 1.0


def test_all_medium_is_half() -> None:
    # Each weight times 0.5 sums to 0.5.
    assert composite_score(_all("medium")) == 0.5


def test_all_low_is_one_fifth() -> None:
    # 0.2 * sum_of_weights = 0.2 * 1.0 = 0.2.
    assert composite_score(_all("low")) == 0.2


def test_all_high_is_eight_tenths() -> None:
    assert composite_score(_all("high")) == 0.8


def test_only_b_critical() -> None:
    # B weight is 0.30 — only B is critical, the rest are none.
    assert composite_score(_mix(B_data_leakage="critical")) == 0.30


def test_only_a_critical() -> None:
    # A weight is 0.10.
    assert composite_score(_mix(A_prompt_injection="critical")) == 0.10


def test_b_high_c_high_others_low() -> None:
    # 0.30*0.8 + 0.25*0.8 + 0.10*0.2 + 0.20*0.2 + 0.15*0.2
    # = 0.24 + 0.20 + 0.02 + 0.04 + 0.03 = 0.53
    score = composite_score(
        _mix(
            A_prompt_injection="low",
            B_data_leakage="high",
            C_capability_conflict="high",
            D_cascading_error="low",
            E_compliance="low",
        )
    )
    assert score == 0.53


def test_returns_value_in_unit_interval() -> None:
    for sev in SEVERITY_SCORES:
        score = composite_score(_all(sev))
        assert 0.0 <= score <= 1.0


def test_rounded_to_four_decimals() -> None:
    score = composite_score(
        _mix(
            A_prompt_injection="low",  # 0.10 * 0.2 = 0.02
            B_data_leakage="medium",  # 0.30 * 0.5 = 0.15
            C_capability_conflict="medium",  # 0.25 * 0.5 = 0.125
            D_cascading_error="low",  # 0.20 * 0.2 = 0.04
            E_compliance="low",  # 0.15 * 0.2 = 0.03
        )
    )
    # Total = 0.365, already <= 4dp.
    assert score == 0.365
    # The round/4 contract — no more than 4 decimals:
    s = repr(score)
    if "." in s:
        assert len(s.split(".")[1]) <= 4


def test_deterministic_repeat_calls() -> None:
    sv = _mix(B_data_leakage="high", C_capability_conflict="medium")
    out = {composite_score(sv) for _ in range(50)}
    assert len(out) == 1
