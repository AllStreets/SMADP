"""5xx forever -> 6 attempts -> exhausted + webhook.delivery_exhausted journal entry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys, store as tenancy
from smadp.transparency import journal
from smadp.webhooks import deliveries, dispatcher, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    # Monkeypatch time to a base value so tests can control it from there
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    return Config()


@respx.mock
def test_503_forever_marks_exhausted_and_writes_transparency_event(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
):
    ws = tenancy.create_workspace(name="X", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    store.create_subscription(
        workspace_id=ws.id, url="https://hook/x",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=ws.id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    respx.post("https://hook/x").mock(return_value=httpx.Response(503))

    cur = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)

    def _set_now(dt: datetime) -> None:
        monkeypatch.setattr(deliveries, "_now", lambda: dt)
        monkeypatch.setattr(worker, "_now", lambda: dt)

    for _ in range(6):
        _set_now(cur)
        worker.process_one_pending(config=cfg)
        cur += timedelta(seconds=300)

    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 1
    assert rows[0].status == DeliveryStatus.EXHAUSTED
    assert rows[0].attempts == 6

    types = [ev.event_type for ev in journal.iter_events(config=cfg)]
    assert "webhook.delivery_exhausted" in types
