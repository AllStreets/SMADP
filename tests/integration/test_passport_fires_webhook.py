"""Passport renders MUST fire a passport.generated webhook event."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


def test_render_passport_enqueues_one_delivery_per_matching_subscription(
    cfg: Config, workspace_id: str
):
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://a/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://b/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    render_passport(
        verdict={
            "verdict_id": "vdt_FIRE",
            "pair": ["a/x", "b/y"],
            "headline": "Fire",
            "composite_score": 0.5,
            "framework_mappings": {},
        },
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=workspace_id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 2
    assert {r.event_type for r in rows} == {EventType.PASSPORT_GENERATED}
    assert {r.status for r in rows} == {DeliveryStatus.PENDING}


def test_render_passport_with_no_subscriptions_writes_zero_rows(cfg: Config, workspace_id: str):
    render_passport(
        verdict={
            "verdict_id": "vdt_X",
            "pair": ["a/x", "b/y"],
            "headline": "X",
            "composite_score": 0.5,
            "framework_mappings": {},
        },
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=workspace_id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )
    assert list(deliveries.iter_all(config=cfg)) == []
