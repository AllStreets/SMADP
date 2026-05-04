"""Golden tests: byte-stable Vanta/Drata/Slack translated payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from smadp.integrations import get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope

_FIXED_ENVELOPE = WebhookEnvelope(
    id="evt_20260503120000_abcdef",
    type=EventType.PASSPORT_GENERATED,
    created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
    workspace_id="ws_GOLDEN12",
    data={
        "verdict_id": "vdt_GOLDEN",
        "agent_pair": ["anthropic/claude", "openai/gpt"],
        "composite_score": 0.42,
        "passport_url": "https://smadp.example/passports/vdt_GOLDEN.html",
    },
    signature_meta={"transparency_log_id": 7},
)


_VANTA_EXPECTED = (
    b'{"evidenceId":"vdt_GOLDEN",'
    b'"evidenceRequestId":"req_GOLDEN",'
    b'"evidenceType":"smadp_passport",'
    b'"metadata":{"agent_pair":["anthropic/claude","openai/gpt"],'
    b'"composite_score":0.42,'
    b'"passport_url":"https://smadp.example/passports/vdt_GOLDEN.html",'
    b'"verdict_id":"vdt_GOLDEN"},'
    b'"passedAt":"2026-05-03T12:00:00Z"}'
)


_DRATA_EXPECTED = (
    b'{"controlId":"ctrl_GOLDEN",'
    b'"evidence":{"event_type":"passport.generated",'
    b'"passport_url":"https://smadp.example/passports/vdt_GOLDEN.html",'
    b'"score":0.42,'
    b'"verdict_id":"vdt_GOLDEN"},'
    b'"occurredAt":"2026-05-03T12:00:00Z"}'
)


_SLACK_EXPECTED = (
    b'{"blocks":[{"text":{"text":"Passport generated for vdt_GOLDEN",'
    b'"type":"plain_text"},"type":"header"},'
    b'{"fields":[{"text":"*Verdict ID:* `vdt_GOLDEN`","type":"mrkdwn"},'
    b'{"text":"*Pair:* `anthropic/claude` \\u2194 `openai/gpt`","type":"mrkdwn"},'
    b'{"text":"*Score:* 0.42","type":"mrkdwn"},'
    b'{"text":"*Event:* `passport.generated`","type":"mrkdwn"}],"type":"section"},'
    b'{"elements":[{"text":{"text":"Open passport","type":"plain_text"},'
    b'"type":"button","url":"https://smadp.example/passports/vdt_GOLDEN.html"}],'
    b'"type":"actions"}],'
    b'"text":"Passport generated for vdt_GOLDEN"}'
)


def test_vanta_golden():
    adapter = get_adapter(IntegrationKind.VANTA)
    body = adapter.translate(
        _FIXED_ENVELOPE, config={"token": "tok", "evidence_request_id": "req_GOLDEN"}
    )
    assert body == _VANTA_EXPECTED


def test_drata_golden():
    adapter = get_adapter(IntegrationKind.DRATA)
    body = adapter.translate(_FIXED_ENVELOPE, config={"token": "tok", "control_id": "ctrl_GOLDEN"})
    assert body == _DRATA_EXPECTED


def test_slack_golden():
    adapter = get_adapter(IntegrationKind.SLACK)
    body = adapter.translate(_FIXED_ENVELOPE, config={})
    assert body == _SLACK_EXPECTED
