"""Unit tests for VantaAdapter translator."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


def _envelope(event_type: EventType = EventType.PASSPORT_GENERATED) -> WebhookEnvelope:
    return WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=event_type,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={
            "verdict_id": "vdt_X",
            "composite_score": 0.42,
            "passport_url": "https://smadp.example/passports/vdt_X.html",
        },
        signature_meta={"transparency_log_id": 7},
    )


def test_vanta_translator_payload_shape():
    adapter = get_adapter(IntegrationKind.VANTA)
    body = adapter.translate(_envelope(), config={"token": "tok", "evidence_request_id": "req_1"})
    obj = json.loads(body)
    assert obj["evidenceType"] == "smadp_passport"
    assert obj["evidenceId"] == "vdt_X"
    assert obj["passedAt"] == "2026-05-03T12:00:00Z"
    assert obj["evidenceRequestId"] == "req_1"
    assert obj["metadata"]["composite_score"] == 0.42


def test_vanta_translator_missing_token_raises():
    adapter = get_adapter(IntegrationKind.VANTA)
    with pytest.raises(ValueError, match="token"):
        adapter.translate(_envelope(), config={"evidence_request_id": "req_1"})


def test_vanta_translator_missing_request_id_raises():
    adapter = get_adapter(IntegrationKind.VANTA)
    with pytest.raises(ValueError, match="evidence_request_id"):
        adapter.translate(_envelope(), config={"token": "tok"})


def test_vanta_headers_authorization_bearer():
    adapter = get_adapter(IntegrationKind.VANTA)
    h = adapter.headers(_envelope(), config={"token": "abc123", "evidence_request_id": "req_1"})
    assert h == {"Authorization": "Bearer abc123", "Content-Type": "application/json"}


def test_vanta_translator_handles_missing_data_fields():
    adapter = get_adapter(IntegrationKind.VANTA)
    env = WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.VERDICT_UPDATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={},
        signature_meta={"transparency_log_id": 7},
    )
    body = adapter.translate(env, config={"token": "tok", "evidence_request_id": "req_1"})
    obj = json.loads(body)
    assert obj["evidenceId"] == "n/a"
