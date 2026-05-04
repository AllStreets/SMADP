"""Byte-stable crosswalk golden against fixture.

Locks the exact intersection of the seed frameworks meta with the full risk
taxonomy. Any change to controls.applies_to_risks (in any of the 11
frameworks) must be paired with a refreshed golden file.
"""

from __future__ import annotations

import json
from pathlib import Path

from smadp.frameworks.crosswalk import (
    compute_framework_coverage,
    load_frameworks_meta,
)

GOLDEN = Path(__file__).parent / "golden" / "coverage_full.json"


def test_full_risk_coverage_matches_golden() -> None:
    meta = load_frameworks_meta()
    risks = [
        "A_prompt_injection",
        "B_data_leakage",
        "C_capability_conflict",
        "D_cascading_error",
        "E_compliance",
    ]
    actual = compute_framework_coverage(verdict_risks=risks, frameworks_meta=meta)
    expected = json.loads(GOLDEN.read_text("utf-8"))
    assert actual == expected
