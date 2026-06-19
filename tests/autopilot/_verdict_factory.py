"""Shared helper: build a schema-valid Verdict JSON string for approve tests.

The operator approve gate (``approve_one``) now rejects verdicts that fail
``Verdict`` schema validation, so fixtures must write valid verdicts.
"""

from __future__ import annotations

import json

from smadp.utils.slug import sort_pair

_RISK_KEYS = (
    "A_prompt_injection",
    "B_data_leakage",
    "C_capability_conflict",
    "D_cascading_error",
    "E_compliance",
)


def valid_verdict_json(a: str, b: str, *, key: str | None = None) -> str:
    """Return a schema-valid Verdict as a JSON string for the pair (a, b)."""
    a, b = sort_pair(a, b)
    verdict_id = key or f"v_2026-06-01_{a}__{b}_000000"
    sub_verdicts = {
        risk: {
            "severity": "low",
            "rationale": f"{a} and {b} interaction for {risk}.",
            "citations": [{"profile_field": f"{a}.capabilities.use_mcp"}],
            "conditions": [],
            "mitigations": [],
        }
        for risk in _RISK_KEYS
    }
    verdict = {
        "schema_version": "1.0",
        "pair": [a, b],
        "verdict_id": verdict_id,
        "generated_at": "2026-06-01T00:00:00Z",
        "model": {"name": "test", "id": "test-v1", "rubric_version": "1.0"},
        "evidence_level": "docs-only",
        "confidence": 0.5,
        "composite_score": 0.3,
        "headline": f"{a} x {b}: low risk overall.",
        "sub_verdicts": sub_verdicts,
        "framework_mappings": {},
        "reproducibility": {
            "rubric_url": "/_meta/rubric/1.0.json",
            "profile_a_hash": "sha256:" + "0" * 64,
            "profile_b_hash": "sha256:" + "0" * 64,
            "evidence_bundle_hash": "sha256:" + "0" * 64,
        },
        "sandbox_runs": [],
    }
    return json.dumps(verdict)
