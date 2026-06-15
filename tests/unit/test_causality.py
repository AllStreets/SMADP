"""Causal risk DAG + deterministic amplification/leverage.

The golden numbers in this file are the cross-language parity contract with
``site/tests/lib/causality.test.ts`` — they MUST stay identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.analyzer.causality import (
    RISK_IDS,
    CausalityDag,
    CausalityError,
    compute_causality,
    load_causality_dag,
)

DAG_PATH = Path(__file__).resolve().parents[2] / "catalog" / "_meta" / "risk-causality.json"


def _dag() -> CausalityDag:
    return load_causality_dag(DAG_PATH)


def test_shipped_dag_loads_acyclic_with_a_to_b_edge() -> None:
    dag = _dag()
    assert set(dag.nodes) == set(RISK_IDS)
    pairs = {(e.src, e.dst) for e in dag.edges}
    assert ("A_prompt_injection", "B_data_leakage") in pairs


def test_cyclic_dag_rejected() -> None:
    bad = {
        "nodes": list(RISK_IDS),
        "edges": [
            {"from": "A_prompt_injection", "to": "B_data_leakage", "mechanism": "m"},
            {"from": "B_data_leakage", "to": "A_prompt_injection", "mechanism": "m"},
        ],
    }
    with pytest.raises(CausalityError):
        CausalityDag.from_dict(bad)


def test_case_one_amplification_leverage_and_best() -> None:
    dag = _dag()
    severities = {
        "A_prompt_injection": "high",
        "B_data_leakage": "medium",
        "C_capability_conflict": "none",
        "D_cascading_error": "low",
        "E_compliance": "none",
    }
    report = compute_causality(severities, dag)
    amp = {(e.src, e.dst): e.amplification for e in report.edges}
    active = {(e.src, e.dst): e.active for e in report.edges}

    assert amp[("A_prompt_injection", "B_data_leakage")] == 0.4
    assert active[("A_prompt_injection", "B_data_leakage")] is True
    assert amp[("A_prompt_injection", "D_cascading_error")] == 0.16
    assert active[("A_prompt_injection", "D_cascading_error")] is True
    assert amp[("B_data_leakage", "E_compliance")] == 0.0
    assert active[("B_data_leakage", "E_compliance")] is False

    assert report.leverage == {
        "A_prompt_injection": 1.5,
        "B_data_leakage": 0.5,
        "C_capability_conflict": 0.0,
        "D_cascading_error": 0.2,
        "E_compliance": 0.0,
    }
    assert report.best_mitigation == "A_prompt_injection"


def test_all_none_has_no_best_mitigation() -> None:
    dag = _dag()
    severities = dict.fromkeys(RISK_IDS, "none")
    report = compute_causality(severities, dag)
    assert report.best_mitigation is None
    assert all(v == 0.0 for v in report.leverage.values())


def test_case_b_critical_e_high() -> None:
    dag = _dag()
    severities = {
        "A_prompt_injection": "none",
        "B_data_leakage": "critical",
        "C_capability_conflict": "none",
        "D_cascading_error": "none",
        "E_compliance": "high",
    }
    report = compute_causality(severities, dag)
    amp = {(e.src, e.dst): e.amplification for e in report.edges}
    assert amp[("B_data_leakage", "E_compliance")] == 0.8
    assert report.leverage["B_data_leakage"] == 1.8
    assert report.best_mitigation == "B_data_leakage"


def test_payload_shape() -> None:
    dag = _dag()
    severities = {
        "A_prompt_injection": "high",
        "B_data_leakage": "medium",
        "C_capability_conflict": "none",
        "D_cascading_error": "low",
        "E_compliance": "none",
    }
    payload = compute_causality(severities, dag).to_payload()
    assert set(payload.keys()) == {"edges", "leverage", "best_mitigation", "severities"}
    edge0 = payload["edges"][0]
    assert set(edge0.keys()) == {"from", "to", "mechanism", "amplification", "active"}
    assert payload["severities"]["A_prompt_injection"] == "high"
