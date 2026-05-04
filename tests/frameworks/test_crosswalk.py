"""Tests for smadp.frameworks.crosswalk — deterministic supplemental coverage."""

from __future__ import annotations

from smadp.frameworks.crosswalk import (
    compute_framework_coverage,
    framework_coverage_delta,
    load_frameworks_meta,
)


def test_load_frameworks_meta_returns_all_eleven() -> None:
    meta = load_frameworks_meta()
    assert len(meta) == 11
    assert "owasp_llm_top_10" in meta


def test_coverage_intersects_risks_and_controls() -> None:
    meta = load_frameworks_meta()
    risks = ["A_prompt_injection", "B_data_leakage"]
    coverage = compute_framework_coverage(verdict_risks=risks, frameworks_meta=meta)
    # OWASP LLM01 (A) + LLM02 (B) + LLM08 (A) should be hit
    assert "owasp_llm_top_10" in coverage
    owasp = set(coverage["owasp_llm_top_10"])
    assert {"LLM01", "LLM02", "LLM08"}.issubset(owasp)
    # LLM09 (D only) should NOT be hit
    assert "LLM09" not in owasp


def test_coverage_empty_for_empty_risks() -> None:
    meta = load_frameworks_meta()
    assert compute_framework_coverage(verdict_risks=[], frameworks_meta=meta) == {}


def test_coverage_is_deterministic_and_sorted() -> None:
    meta = load_frameworks_meta()
    risks = ["A_prompt_injection", "B_data_leakage", "E_compliance"]
    a = compute_framework_coverage(verdict_risks=risks, frameworks_meta=meta)
    b = compute_framework_coverage(verdict_risks=list(reversed(risks)), frameworks_meta=meta)
    assert a == b
    for _fw_id, ctrl_list in a.items():
        assert ctrl_list == sorted(ctrl_list)


def test_delta_added_and_removed() -> None:
    old = {"owasp_llm_top_10": ["LLM01"], "soc_2": ["CC6.1"]}
    new = {"owasp_llm_top_10": ["LLM01", "LLM02"], "hipaa": ["164.308"]}
    delta = framework_coverage_delta(old=old, new=new)
    assert delta == {
        "added": {"owasp_llm_top_10": ["LLM02"], "hipaa": ["164.308"]},
        "removed": {"soc_2": ["CC6.1"]},
    }


def test_delta_empty_when_unchanged() -> None:
    old = {"owasp_llm_top_10": ["LLM01"]}
    assert framework_coverage_delta(old=old, new=dict(old)) == {"added": {}, "removed": {}}
