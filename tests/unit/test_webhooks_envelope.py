"""Unit tests for envelope builder + HMAC."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from smadp.schemas.webhooks import EventType
from smadp.webhooks.envelope import (
    build_envelope,
    canonical_envelope_bytes,
    compute_hmac,
)


def test_canonical_bytes_are_sorted_and_compact():
    env = build_envelope(
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
        workspace_id="ws_ABCD1234",
        data={"z": 1, "a": 2},
        signature_meta={"transparency_log_id": 7},
    )
    raw = canonical_envelope_bytes(env)
    obj = json.loads(raw)
    # Round-trip preserves all keys.
    assert set(obj.keys()) == {
        "created_at",
        "data",
        "id",
        "signature_meta",
        "type",
        "workspace_id",
    }
    # Compact: no whitespace.
    assert b" " not in raw
    assert b"\n" not in raw
    # Top-level keys are sorted.
    keys_in_order = [
        s.split(b'":')[0].lstrip(b'{"').rstrip(b'"')
        for s in raw.split(b',"')
    ]
    assert keys_in_order == sorted(keys_in_order)


def test_canonical_bytes_byte_stable_across_calls():
    args = dict(
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
        workspace_id="ws_ABCD1234",
        data={"a": 1, "b": [1, 2, {"c": 3}]},
        signature_meta={"transparency_log_id": 7, "prev_event_hash": "sha256:" + "0" * 64},
    )
    a = canonical_envelope_bytes(build_envelope(**args))
    b = canonical_envelope_bytes(build_envelope(**args))
    assert a == b


def test_hmac_matches_hand_computed_reference():
    body = b'{"hello":"world"}'
    secret = "swordfish"
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert compute_hmac(secret, body) == f"sha256={expected}"


def test_hmac_constant_format():
    # Always lowercase hex; always sha256= prefix.
    sig = compute_hmac("k", b"x")
    assert sig.startswith("sha256=")
    hex_part = sig[len("sha256=") :]
    assert hex_part == hex_part.lower()
    assert len(hex_part) == 64
