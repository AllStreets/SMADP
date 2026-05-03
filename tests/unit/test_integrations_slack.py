"""Unit tests for SlackAdapter translator."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


def _passport_envelope() -> WebhookEnvelope:
    return WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={
            "verdict_id": "vdt_X",
            "composite_score": 0.42,
            "passport_url": "https://smadp.example/passports/vdt_X.html",
            "agent_pair": ["a/x", "b/y"],
        },
        signature_meta={"transparency_log_id": 7},
    )


def test_slack_passport_message_shape():
    adapter = get_adapter(IntegrationKind.SLACK)
    body = adapter.translate(_passport_envelope(), config={})
    obj = json.loads(body)
    assert "text" in obj
    assert "Passport generated" in obj["text"]
    assert isinstance(obj["blocks"], list)
    assert any("vdt_X" in json.dumps(b) for b in obj["blocks"])


def test_slack_verdict_message_shape():
    env = WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.VERDICT_UPDATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={"verdict_id": "vdt_Y", "agent_pair": ["a/x", "b/y"], "composite_score": 0.7},
        signature_meta={"transparency_log_id": 1},
    )
    adapter = get_adapter(IntegrationKind.SLACK)
    obj = json.loads(adapter.translate(env, config={}))
    assert "Verdict updated" in obj["text"]
    assert any("a/x" in json.dumps(b) for b in obj["blocks"])


def test_slack_no_passport_url_omits_button():
    env = WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={"verdict_id": "vdt_X"},
        signature_meta={"transparency_log_id": 7},
    )
    adapter = get_adapter(IntegrationKind.SLACK)
    obj = json.loads(adapter.translate(env, config={}))
    flat = json.dumps(obj)
    assert "actions" not in flat or "button" not in flat


def test_slack_headers_minimal():
    adapter = get_adapter(IntegrationKind.SLACK)
    h = adapter.headers(_passport_envelope(), config={})
    assert h == {"Content-Type": "application/json"}
