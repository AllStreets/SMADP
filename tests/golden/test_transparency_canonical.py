"""Golden test: the canonical signing input for SignedEvents is byte-stable.

Any change to ``_canonical_signing_input`` would invalidate every
existing transparency log. The expected bytes here are the contract.
"""

from __future__ import annotations

from datetime import datetime, timezone

from smadp.schemas.transparency import SignedEvent
from smadp.transparency.journal import _canonical_payload, _canonical_signing_input


def test_canonical_payload_byte_stable():
    a = _canonical_payload({"alpha": 1, "beta": [2, 3], "gamma": {"x": "y"}})
    b = _canonical_payload({"gamma": {"x": "y"}, "beta": [2, 3], "alpha": 1})
    assert a == b
    assert a == b'{"alpha":1,"beta":[2,3],"gamma":{"x":"y"}}'


def test_canonical_signing_input_byte_stable():
    ev = SignedEvent(
        id=42,
        event_type="verdict.created",
        payload={"verdict_id": "vdt_x", "score": 0.31},
        ts=datetime(2026, 5, 3, 12, 34, 56, 789000, tzinfo=timezone.utc),
        prev_hash="sha256:" + "0" * 64,
        signature="aabbccdd",
    )
    out = _canonical_signing_input(ev)
    assert out == (
        b'{"event_type":"verdict.created","id":42,'
        b'"payload":{"score":0.31,"verdict_id":"vdt_x"},'
        b'"prev_hash":"sha256:00000000000000000000000000000000'
        b'00000000000000000000000000000000",'
        b'"ts":"2026-05-03T12:34:56.789Z"}'
    )


def test_canonical_signing_input_omits_signature_and_rekor():
    """The signing input is what gets signed — it must not include the
    signature itself or the rekor_uuid (which is set after signing)."""
    ev = SignedEvent(
        id=1,
        event_type="x",
        payload={},
        ts=datetime(2026, 5, 3, tzinfo=timezone.utc),
        prev_hash="sha256:" + "0" * 64,
        signature="aa",
        rekor_uuid="should-not-appear",
    )
    out = _canonical_signing_input(ev)
    assert b"signature" not in out
    assert b"rekor" not in out
    assert b"should-not-appear" not in out
