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
