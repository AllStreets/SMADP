"""Byte-stable canonical passport payload — what the signature attests to."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_passport_payload(
    *,
    verdict: dict[str, Any],
    frameworks: dict[str, Any],
    evidence_index: dict[str, Any],
    rendered_at: str,
) -> bytes:
    """Return the canonical bytes that the passport signature attests to.

    Sorted keys, no whitespace, UTF-8. Deterministic across dict iteration order.
    """
    canonical = {
        "evidence_index": evidence_index,
        "frameworks": frameworks,
        "rendered_at": rendered_at,
        "verdict": verdict,
    }
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_passport_sha256(
    *,
    verdict: dict[str, Any],
    frameworks: dict[str, Any],
    evidence_index: dict[str, Any],
    rendered_at: str,
) -> str:
    """sha256 of the canonical payload bytes, formatted as ``sha256:<hex>``."""
    payload = canonical_passport_payload(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        rendered_at=rendered_at,
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = ["canonical_passport_payload", "canonical_passport_sha256"]
