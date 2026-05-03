"""Golden tests for ``composite_score`` — locks the scoring formula.

A change to weights or severity scores will break these tests. That is
intentional: the formula is part of the public contract and any
modification needs an explicit, reviewed update to the golden table
(and a chronicle entry per §9 of the spec).
"""

from __future__ import annotations

import pytest

from smadp.analyzer.scoring import composite_score
from smadp.schemas.verdict import Citation, Severity, SubVerdict, SubVerdicts

# Each row: (case-name, severities-by-risk, expected composite score).
# Severities cover all five risks exactly: A, B, C, D, E.
GOLDEN_CASES: list[tuple[str, dict[str, Severity], float]] = [
    (
        "all-none",
        {"A": "none", "B": "none", "C": "none", "D": "none", "E": "none"},
        0.0,
    ),
    (
        "all-low",
        {"A": "low", "B": "low", "C": "low", "D": "low", "E": "low"},
        0.2,
    ),
    (
        "all-medium",
        {"A": "medium", "B": "medium", "C": "medium", "D": "medium", "E": "medium"},
        0.5,
    ),
    (
        "all-high",
        {"A": "high", "B": "high", "C": "high", "D": "high", "E": "high"},
        0.8,
    ),
    (
        "all-critical",
        {"A": "critical", "B": "critical", "C": "critical", "D": "critical", "E": "critical"},
        1.0,
    ),
    (
        "only-A-critical",
        {"A": "critical", "B": "none", "C": "none", "D": "none", "E": "none"},
        0.10,  # weight A
    ),
    (
        "only-B-critical",
        {"A": "none", "B": "critical", "C": "none", "D": "none", "E": "none"},
        0.30,
    ),
    (
        "only-C-critical",
        {"A": "none", "B": "none", "C": "critical", "D": "none", "E": "none"},
        0.25,
    ),
    (
        "only-D-critical",
        {"A": "none", "B": "none", "C": "none", "D": "critical", "E": "none"},
        0.20,
    ),
    (
        "only-E-critical",
        {"A": "none", "B": "none", "C": "none", "D": "none", "E": "critical"},
        0.15,
    ),
    (
        "B-high-C-high-rest-low",
        {"A": "low", "B": "high", "C": "high", "D": "low", "E": "low"},
        # 0.10*0.2 + 0.30*0.8 + 0.25*0.8 + 0.20*0.2 + 0.15*0.2
        # = 0.02 + 0.24 + 0.20 + 0.04 + 0.03 = 0.53
        0.53,
    ),
    (
        "mixed-1",
        {"A": "low", "B": "medium", "C": "medium", "D": "low", "E": "low"},
        # 0.10*0.2 + 0.30*0.5 + 0.25*0.5 + 0.20*0.2 + 0.15*0.2
        # = 0.02 + 0.15 + 0.125 + 0.04 + 0.03 = 0.365
        0.365,
    ),
    (
        "mixed-2",
        {"A": "high", "B": "medium", "C": "low", "D": "medium", "E": "high"},
        # 0.10*0.8 + 0.30*0.5 + 0.25*0.2 + 0.20*0.5 + 0.15*0.8
        # = 0.08 + 0.15 + 0.05 + 0.10 + 0.12 = 0.50
        0.50,
    ),
    (
        "mixed-3",
        {"A": "none", "B": "critical", "C": "high", "D": "medium", "E": "low"},
        # 0.10*0.0 + 0.30*1.0 + 0.25*0.8 + 0.20*0.5 + 0.15*0.2
        # = 0.0 + 0.30 + 0.20 + 0.10 + 0.03 = 0.63
        0.63,
    ),
]


def _stub_sv(severity: Severity) -> SubVerdict:
    return SubVerdict(
        severity=severity,
        rationale="placeholder rationale",
        citations=[Citation(profile_field="agent_a.capabilities.execute_shell")],
    )


def _build(severities: dict[str, Severity]) -> SubVerdicts:
    return SubVerdicts(
        A_prompt_injection=_stub_sv(severities["A"]),
        B_data_leakage=_stub_sv(severities["B"]),
        C_capability_conflict=_stub_sv(severities["C"]),
        D_cascading_error=_stub_sv(severities["D"]),
        E_compliance=_stub_sv(severities["E"]),
    )


@pytest.mark.parametrize(
    "name, severities, expected",
    GOLDEN_CASES,
    ids=[c[0] for c in GOLDEN_CASES],
)
def test_golden(name: str, severities: dict[str, Severity], expected: float) -> None:
    score = composite_score(_build(severities))
    assert score == pytest.approx(expected, abs=1e-9), (
        f"{name}: composite_score changed unexpectedly. If this is intentional, "
        "update the golden table in tests/golden/test_scoring_golden.py and add "
        "a chronicle entry."
    )
