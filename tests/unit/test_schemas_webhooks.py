"""Unit tests for smadp.schemas.webhooks."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from smadp.schemas.webhooks import (
    DeliveryStatus,
    EventType,
    Subscription,
    WebhookDelivery,
    WebhookEnvelope,
)


def test_event_type_values_are_locked():
    """Locked-down enum: any rename is a contract break."""
    assert {e.value for e in EventType} == {
        "verdict.created",
        "verdict.updated",
        "verdict.expired",
        "framework_coverage.changed",
        "passport.generated",
        "passport.revoked",
    }


def test_delivery_status_values_are_locked():
    assert {s.value for s in DeliveryStatus} == {
        "pending",
        "running",
        "delivered",
        "failed",
        "exhausted",
    }


def test_subscription_id_pattern_enforced():
    with pytest.raises(ValidationError):
        Subscription(
            id="bad-id",
            workspace_id="ws_ABCD1234",
            url="https://example.com/wh",
            event_types=[EventType.PASSPORT_GENERATED],
            active=True,
            created_at=datetime.now(timezone.utc),
        )


def test_subscription_url_must_be_https_or_localhost():
    with pytest.raises(ValidationError):
        Subscription(
            id="sub_AB12CD34",
            workspace_id="ws_ABCD1234",
            url="ftp://example.com/wh",
            event_types=[EventType.PASSPORT_GENERATED],
            active=True,
            created_at=datetime.now(timezone.utc),
        )


def test_subscription_accepts_http_localhost_for_dev():
    """http://localhost is allowed (dev/test); other http URLs are not."""
    Subscription(
        id="sub_AB12CD34",
        workspace_id="ws_ABCD1234",
        url="http://localhost:9000/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        active=True,
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValidationError):
        Subscription(
            id="sub_AB12CD34",
            workspace_id="ws_ABCD1234",
            url="http://example.com/wh",
            event_types=[EventType.PASSPORT_GENERATED],
            active=True,
            created_at=datetime.now(timezone.utc),
        )


def test_subscription_event_types_must_be_nonempty():
    with pytest.raises(ValidationError):
        Subscription(
            id="sub_AB12CD34",
            workspace_id="ws_ABCD1234",
            url="https://example.com/wh",
            event_types=[],
            active=True,
            created_at=datetime.now(timezone.utc),
        )


def test_webhook_delivery_id_pattern_enforced():
    with pytest.raises(ValidationError):
        WebhookDelivery(
            id="bad",
            subscription_id="sub_AB12CD34",
            event_id="evt_20260503120000_abc123",
            event_type=EventType.PASSPORT_GENERATED,
            body=b'{"x":1}',
            status=DeliveryStatus.PENDING,
            attempts=0,
            next_attempt_at=datetime.now(timezone.utc),
            last_error=None,
            created_at=datetime.now(timezone.utc),
            delivered_at=None,
        )


def test_webhook_envelope_requires_required_keys():
    with pytest.raises(ValidationError):
        WebhookEnvelope(
            id="evt_20260503120000_abc123",
            type=EventType.PASSPORT_GENERATED,
            created_at=datetime.now(timezone.utc),
            workspace_id="ws_ABCD1234",
            data={"verdict_id": "vdt_X"},
            signature_meta={},  # missing transparency_log_id
        )


def test_webhook_envelope_round_trip():
    env = WebhookEnvelope(
        id="evt_20260503120000_abc123",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
        workspace_id="ws_ABCD1234",
        data={"verdict_id": "vdt_X"},
        signature_meta={"transparency_log_id": 7, "prev_event_hash": "sha256:" + "0" * 64},
    )
    again = WebhookEnvelope.model_validate(env.model_dump(mode="json"))
    assert again == env
