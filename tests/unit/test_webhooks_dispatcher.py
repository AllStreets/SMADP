"""Unit tests for the webhook dispatcher."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import EventType
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, dispatcher, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_dispatch_event_inserts_one_row_per_matching_subscription(
    cfg: Config, workspace_id: str
):
    sub_a, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    sub_b, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://b/wh",
        event_types=[EventType.PASSPORT_GENERATED, EventType.VERDICT_UPDATED],
        config=cfg,
    )
    sub_c, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://c/wh",
        event_types=[EventType.VERDICT_UPDATED], config=cfg,
    )
    n = dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 7},
        config=cfg,
    )
    assert n == 2  # sub_a + sub_b match
    rows = list(deliveries.iter_all(config=cfg))
    sub_ids_in_rows = {r.subscription_id for r in rows}
    assert sub_ids_in_rows == {sub_a.id, sub_b.id}
    assert sub_c.id not in sub_ids_in_rows


def test_dispatch_event_inserts_zero_when_no_subscriptions(
    cfg: Config, workspace_id: str
):
    n = dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 7},
        config=cfg,
    )
    assert n == 0
    assert list(deliveries.iter_all(config=cfg)) == []


def test_dispatch_event_skips_inactive_subscriptions(
    cfg: Config, workspace_id: str
):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    store.deactivate_subscription(subscription_id=sub.id, config=cfg)
    n = dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 7},
        config=cfg,
    )
    assert n == 0


def test_dispatch_event_writes_canonical_envelope_bytes(
    cfg: Config, workspace_id: str
):
    """The body stored in webhook_deliveries equals canonical envelope bytes."""
    import json

    store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X", "headline": "Hi"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 7, "prev_event_hash": "sha256:" + "0" * 64},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    body = rows[0].body
    parsed = json.loads(body)
    assert parsed["type"] == "passport.generated"
    assert parsed["data"] == {"verdict_id": "vdt_X", "headline": "Hi"}
    assert parsed["workspace_id"] == workspace_id
    assert parsed["signature_meta"]["transparency_log_id"] == 7


def test_dispatch_event_id_is_unique_across_calls(cfg: Config, workspace_id: str):
    import json

    store.create_subscription(
        workspace_id=workspace_id, url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED, payload={}, workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1}, config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED, payload={}, workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 2}, config=cfg,
    )
    ids = {json.loads(r.body)["id"] for r in deliveries.iter_all(config=cfg)}
    assert len(ids) == 2
