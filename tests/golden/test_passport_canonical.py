"""Golden test pinning byte-exact canonical passport payload."""

from __future__ import annotations

import hashlib
import json

from smadp.passport.canonical import (
    canonical_passport_payload,
    canonical_passport_sha256,
)


def test_canonical_payload_is_sorted_compact_utf8():
    """Canonical bytes must sort keys, drop whitespace, and be UTF-8."""
    verdict_dict = {
        "verdict_id": "vdt_X",
        "pair": ["a/x", "b/y"],
        "composite_score": 0.42,
        "headline": "Test",
        "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
    }
    frameworks_dict = {"nist_ai_rmf": {"name": "NIST AI RMF", "controls": [{"id": "GOVERN-1.1"}]}}
    evidence_index = {"sha256:abc": {"source_url": "https://x"}}
    rendered_at = "2026-05-03T12:34:56Z"

    out = canonical_passport_payload(
        verdict=verdict_dict,
        frameworks=frameworks_dict,
        evidence_index=evidence_index,
        rendered_at=rendered_at,
    )

    # Round-trip through json: must sort keys, no whitespace, ascii-safe.
    expected = json.dumps(
        {
            "evidence_index": evidence_index,
            "frameworks": frameworks_dict,
            "rendered_at": rendered_at,
            "verdict": verdict_dict,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    assert out == expected


def test_canonical_payload_is_deterministic_across_dict_orderings():
    a = canonical_passport_payload(
        verdict={"b": 2, "a": 1},
        frameworks={"x": 1, "a": 2},
        evidence_index={"z": 1, "a": 2},
        rendered_at="2026-05-03T00:00:00Z",
    )
    b = canonical_passport_payload(
        verdict={"a": 1, "b": 2},
        frameworks={"a": 2, "x": 1},
        evidence_index={"a": 2, "z": 1},
        rendered_at="2026-05-03T00:00:00Z",
    )
    assert a == b


def test_canonical_passport_sha256_format():
    out = canonical_passport_sha256(
        verdict={}, frameworks={}, evidence_index={}, rendered_at="2026-01-01T00:00:00Z"
    )
    assert out.startswith("sha256:")
    assert len(out) == 7 + 64  # "sha256:" + 64 hex chars

    # And it should match a manual compute
    payload = canonical_passport_payload(
        verdict={}, frameworks={}, evidence_index={}, rendered_at="2026-01-01T00:00:00Z"
    )
    expected = "sha256:" + hashlib.sha256(payload).hexdigest()
    assert out == expected
