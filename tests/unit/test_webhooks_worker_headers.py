"""Worker merges integration headers; reserved SMADP headers win conflicts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType, IntegrationKind
from smadp.tenancy import keys
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, dispatcher, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="W", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


@respx.mock
def test_worker_merges_overlay_headers(cfg: Config, workspace_id: str):
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://api.drata.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.DRATA,
        integration_config={"token": "tok", "control_id": "ctrl_42"},
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    captured: dict[str, str] = {}

    def _capture(req: httpx.Request) -> httpx.Response:
        for k, v in req.headers.items():
            captured[k.lower()] = v
        return httpx.Response(200)

    respx.post("https://api.drata.com/wh").mock(side_effect=_capture)
    assert worker.process_one_pending(config=cfg) is True

    assert captured.get("authorization") == "Bearer tok"
    assert captured.get("x-drata-source") == "smadp"
    # Reserved headers still present:
    assert captured.get("x-smadp-signature", "").startswith("sha256=")
    assert captured.get("x-smadp-event-type") == "passport.generated"

    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.DELIVERED


@respx.mock
def test_worker_overlay_cannot_override_reserved(cfg: Config, workspace_id: str):
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://api.drata.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.GENERIC,
    )
    # Force a delivery row with a malicious overlay (bypass dispatcher):
    deliveries.enqueue(
        subscription_id=store.list_subscriptions(workspace_id=workspace_id, config=cfg)[0].id,
        event_id="evt_20260503120000_abcdef",
        event_type=EventType.PASSPORT_GENERATED,
        body=b"{}",
        headers_overlay={
            "X-SMADP-Signature": "sha256=DEADBEEF",
            "X-SMADP-Event-Type": "spoofed.event",
            "X-Custom": "ok",
        },
        config=cfg,
    )

    captured: dict[str, str] = {}

    def _capture(req: httpx.Request) -> httpx.Response:
        for k, v in req.headers.items():
            captured[k.lower()] = v
        return httpx.Response(200)

    respx.post("https://api.drata.com/wh").mock(side_effect=_capture)
    assert worker.process_one_pending(config=cfg) is True

    # Reserved headers come from worker, NOT overlay:
    assert captured["x-smadp-event-type"] == "passport.generated"
    assert not captured["x-smadp-signature"].endswith("DEADBEEF")
    # Custom header still passes through:
    assert captured.get("x-custom") == "ok"
