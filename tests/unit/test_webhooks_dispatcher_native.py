"""Unit tests for dispatcher routing native subscriptions through adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import EventType, IntegrationKind
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


def test_dispatch_uses_slack_adapter_for_slack_sub(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://hooks.slack.com/services/abc/def",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.SLACK,
        integration_config={},
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X", "passport_url": "https://smadp.example/p/vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 1
    body = rows[0].body.decode("utf-8")
    obj = json.loads(body)
    assert "Passport generated" in obj["text"]


def test_dispatch_generic_sub_uses_canonical_envelope(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    body = rows[0].body
    assert b'"id":"evt_' in body
    assert b'"workspace_id":"' + workspace_id.encode() + b'"' in body


def test_dispatch_native_sub_persists_headers_overlay(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://api.drata.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.DRATA,
        integration_config={"token": "tok", "control_id": "ctrl_42"},
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X", "composite_score": 0.5},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].headers_overlay == {
        "Authorization": "Bearer tok",
        "X-Drata-Source": "smadp",
        "Content-Type": "application/json",
    }


def test_dispatch_two_subs_translate_independently(cfg: Config, workspace_id: str):
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/generic",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://hooks.slack.com/services/abc/def",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.SLACK,
        integration_config={},
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 2
    bodies = {r.body for r in rows}
    assert any(b'"text":"Passport generated for vdt_X"' in b for b in bodies)
    assert any(b'"workspace_id":"' + workspace_id.encode() + b'"' in b for b in bodies)
