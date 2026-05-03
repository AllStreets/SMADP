"""Unit tests for the webhook subscriptions store."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import EventType
from smadp.tenancy import store as tenancy
from smadp.webhooks import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="WH", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_create_subscription_returns_secret_once(cfg: Config, workspace_id: str):
    sub, secret = store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    assert sub.id.startswith("sub_")
    assert sub.workspace_id == workspace_id
    assert sub.active is True
    assert isinstance(secret, str) and len(secret) >= 32  # entropy floor


def test_load_subscription_secret_roundtrip(cfg: Config, workspace_id: str):
    sub, secret = store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    loaded = store.load_subscription_secret(subscription_id=sub.id, config=cfg)
    assert loaded == secret


def test_list_subscriptions_for_workspace(cfg: Config, workspace_id: str):
    a, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    b, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://b/wh",
        event_types=[EventType.VERDICT_UPDATED],
        config=cfg,
    )
    ids = {s.id for s in store.list_subscriptions(workspace_id=workspace_id, config=cfg)}
    assert ids == {a.id, b.id}


def test_match_subscriptions_by_event_type(cfg: Config, workspace_id: str):
    a, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED, EventType.VERDICT_UPDATED],
        config=cfg,
    )
    _b, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://b/wh",
        event_types=[EventType.VERDICT_UPDATED],
        config=cfg,
    )
    matches = store.match_subscriptions(
        workspace_id=workspace_id,
        event_type=EventType.PASSPORT_GENERATED,
        config=cfg,
    )
    assert {s.id for s in matches} == {a.id}


def test_match_subscriptions_skips_inactive(cfg: Config, workspace_id: str):
    a, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    store.deactivate_subscription(subscription_id=a.id, config=cfg)
    matches = store.match_subscriptions(
        workspace_id=workspace_id,
        event_type=EventType.PASSPORT_GENERATED,
        config=cfg,
    )
    assert matches == []


def test_get_subscription_by_id(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://x/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    loaded = store.get_subscription(subscription_id=sub.id, config=cfg)
    assert loaded == sub


def test_get_subscription_unknown_raises(cfg: Config):
    with pytest.raises(KeyError):
        store.get_subscription(subscription_id="sub_NOPE0000", config=cfg)


def test_load_secret_unknown_raises(cfg: Config):
    with pytest.raises(KeyError):
        store.load_subscription_secret(subscription_id="sub_NOPE0000", config=cfg)
