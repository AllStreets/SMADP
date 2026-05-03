"""Golden test: WebhookEnvelope canonical bytes are byte-stable for fixed input."""

from __future__ import annotations

from datetime import datetime, timezone

from smadp.schemas.webhooks import EventType
from smadp.webhooks.envelope import build_envelope, canonical_envelope_bytes


_FIXED_ARGS = dict(
    event_id="evt_20260503120000_abc123",
    event_type=EventType.PASSPORT_GENERATED,
    created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
    workspace_id="ws_GOLDEN12",
    data={
        "verdict_id": "vdt_GOLDEN",
        "agent_pair": ["anthropic/claude", "openai/gpt"],
        "composite_score": 0.42,
        "trigger": "model_bump",
    },
    signature_meta={
        "transparency_log_id": 7,
        "prev_event_hash": "sha256:" + "0" * 64,
    },
)


_EXPECTED = (
    b'{"created_at":"2026-05-03T12:00:00Z","data":'
    b'{"agent_pair":["anthropic/claude","openai/gpt"],'
    b'"composite_score":0.42,"trigger":"model_bump","verdict_id":"vdt_GOLDEN"},'
    b'"id":"evt_20260503120000_abc123","signature_meta":'
    b'{"prev_event_hash":"sha256:00000000000000000000000000000000'
    b'00000000000000000000000000000000","transparency_log_id":7},'
    b'"type":"passport.generated","workspace_id":"ws_GOLDEN12"}'
)


def test_envelope_bytes_match_golden_fixture():
    actual = canonical_envelope_bytes(build_envelope(**_FIXED_ARGS))
    assert actual == _EXPECTED


def test_envelope_bytes_stable_across_calls():
    a = canonical_envelope_bytes(build_envelope(**_FIXED_ARGS))
    b = canonical_envelope_bytes(build_envelope(**_FIXED_ARGS))
    assert a == b
