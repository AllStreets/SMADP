"""Unit tests for DrataAdapter translator."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


def _envelope() -> WebhookEnvelope:
    return WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={
            "verdict_id": "vdt_X",
            "composite_score": 0.42,
            "passport_url": "https://smadp.example/passports/vdt_X.html",
        },
        signature_meta={"transparency_log_id": 7},
    )


def test_drata_payload_shape():
    adapter = get_adapter(IntegrationKind.DRATA)
    body = adapter.translate(_envelope(), config={"token": "tok", "control_id": "ctrl_42"})
    obj = json.loads(body)
    assert obj["controlId"] == "ctrl_42"
    assert obj["occurredAt"] == "2026-05-03T12:00:00Z"
    assert obj["evidence"]["verdict_id"] == "vdt_X"
    assert obj["evidence"]["score"] == 0.42
    assert obj["evidence"]["passport_url"] == "https://smadp.example/passports/vdt_X.html"


def test_drata_missing_token_raises():
    adapter = get_adapter(IntegrationKind.DRATA)
    with pytest.raises(ValueError, match="token"):
        adapter.translate(_envelope(), config={"control_id": "ctrl_42"})


def test_drata_missing_control_id_raises():
    adapter = get_adapter(IntegrationKind.DRATA)
    with pytest.raises(ValueError, match="control_id"):
        adapter.translate(_envelope(), config={"token": "tok"})


def test_drata_headers():
    adapter = get_adapter(IntegrationKind.DRATA)
    h = adapter.headers(_envelope(), config={"token": "abc", "control_id": "ctrl_42"})
    assert h == {
        "Authorization": "Bearer abc",
        "X-Drata-Source": "smadp",
        "Content-Type": "application/json",
    }
