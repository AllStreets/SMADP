"""4xx response marks delivery failed without retry; no extra rows enqueued."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, dispatcher, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@respx.mock
def test_400_marks_failed_no_retry(cfg: Config):
    ws = tenancy.create_workspace(name="X", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    store.create_subscription(
        workspace_id=ws.id,
        url="https://hook/x",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=ws.id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    route = respx.post("https://hook/x").mock(return_value=httpx.Response(400, text="bad"))

    assert worker.process_one_pending(config=cfg) is True
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.FAILED
    assert "400" in rows[0].last_error
    assert rows[0].attempts == 1

    # Calling again does NOT re-attempt — the row is terminal.
    assert worker.process_one_pending(config=cfg) is False
    assert route.call_count == 1
