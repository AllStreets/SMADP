"""Unit tests for the webhook_deliveries queue (schema + enqueue path)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def subscription_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    sub, _ = store.create_subscription(
        workspace_id=ws.id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    return sub.id


def test_enqueue_creates_pending_row(cfg: Config, subscription_id: str):
    delivery_id = deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b'{"x":1}',
        config=cfg,
    )
    assert delivery_id.startswith("wd_")
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 1
    row = rows[0]
    assert row.id == delivery_id
    assert row.subscription_id == subscription_id
    assert row.event_id == "evt_20260503120000_abc123"
    assert row.event_type == EventType.PASSPORT_GENERATED
    assert row.body == b'{"x":1}'
    assert row.status == DeliveryStatus.PENDING
    assert row.attempts == 0
    assert row.last_error is None
    assert row.delivered_at is None


def test_enqueue_next_attempt_at_is_now_or_past(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].next_attempt_at <= datetime.now(timezone.utc)


def test_iter_all_orders_by_id(cfg: Config, subscription_id: str):
    ids: list[str] = []
    for i in range(3):
        ids.append(
            deliveries.enqueue(
                subscription_id=subscription_id,
                event_id=f"evt_2026050312000{i}_abc123",
                event_type=EventType.PASSPORT_GENERATED,
                body=b"{}",
                config=cfg,
            )
        )
    fetched = [r.id for r in deliveries.iter_all(config=cfg)]
    assert fetched == ids


def test_claim_pending_marks_row_running(cfg: Config, subscription_id: str):
    delivery_id = deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    assert claimed.id == delivery_id
    assert claimed.status == DeliveryStatus.RUNNING
    assert claimed.attempts == 1


def test_claim_pending_returns_none_when_empty(cfg: Config):
    assert deliveries.claim_pending(config=cfg) is None


def test_claim_pending_skips_future_rows(
    cfg: Config, subscription_id: str, monkeypatch: pytest.MonkeyPatch
):
    """Rows whose next_attempt_at is in the future are not claimable."""
    from datetime import timedelta

    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(deliveries, "_now", lambda: far_future - timedelta(days=1))
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    monkeypatch.setattr(deliveries, "_now", lambda: datetime(2050, 1, 1, tzinfo=timezone.utc))
    assert deliveries.claim_pending(config=cfg) is None


def test_claim_pending_does_not_double_claim(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    a = deliveries.claim_pending(config=cfg)
    b = deliveries.claim_pending(config=cfg)
    assert a is not None
    assert b is None  # second claim sees no pending


def test_mark_delivered_sets_status_and_delivered_at(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    deliveries.mark_delivered(delivery_id=claimed.id, config=cfg)
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.DELIVERED
    assert rows[0].delivered_at is not None


def test_mark_failed_sets_status_and_error(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    deliveries.mark_failed(delivery_id=claimed.id, error="HTTP 400 bad request", config=cfg)
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.FAILED
    assert rows[0].last_error == "HTTP 400 bad request"


def test_mark_exhausted_writes_status(cfg: Config, subscription_id: str):
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    deliveries.mark_exhausted(delivery_id=claimed.id, error="HTTP 503 forever", config=cfg)
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.EXHAUSTED
    assert rows[0].last_error == "HTTP 503 forever"


def test_reschedule_pending_arms_for_future_attempt(
    cfg: Config, subscription_id: str, monkeypatch: pytest.MonkeyPatch
):
    """After a 5xx, the worker re-arms a row with next_attempt_at in the future."""
    from datetime import timedelta

    monkeypatch.setattr(
        deliveries, "_now", lambda: datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    )
    deliveries.enqueue(
        subscription_id=subscription_id,
        event_id="evt_20260503120000_abc123",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        config=cfg,
    )
    claimed = deliveries.claim_pending(config=cfg)
    assert claimed is not None
    next_at = datetime(2026, 5, 3, 12, 0, 4, tzinfo=timezone.utc)
    deliveries.reschedule_pending(
        delivery_id=claimed.id,
        next_attempt_at=next_at,
        error="HTTP 503",
        config=cfg,
    )
    # Now claim should still find nothing — current_now < next_attempt_at.
    assert deliveries.claim_pending(config=cfg) is None
    monkeypatch.setattr(
        deliveries, "_now", lambda: datetime(2026, 5, 3, 12, 0, 5, tzinfo=timezone.utc)
    )
    rearmed = deliveries.claim_pending(config=cfg)
    assert rearmed is not None
    assert rearmed.attempts == 2
