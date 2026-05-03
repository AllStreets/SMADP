"""Unit tests for the webhook worker's per-row processor."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
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
    # Monkeypatch time to a base value so tests can control it from there
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


def _enqueue_one(cfg: Config, workspace_id: str, url: str = "https://hook/x") -> str:
    _sub, secret = store.create_subscription(
        workspace_id=workspace_id,
        url=url,
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
    return secret


def test_process_one_pending_returns_false_when_empty(cfg: Config):
    assert worker.process_one_pending(config=cfg) is False


@respx.mock
def test_process_one_pending_2xx_marks_delivered(cfg: Config, workspace_id: str):
    secret = _enqueue_one(cfg, workspace_id)
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["sig"] = request.headers["X-SMADP-Signature"]
        captured["delivery_id"] = request.headers["X-SMADP-Delivery-Id"]
        captured["event_type"] = request.headers["X-SMADP-Event-Type"]
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200)

    respx.post("https://hook/x").mock(side_effect=_capture)
    assert worker.process_one_pending(config=cfg) is True

    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.DELIVERED
    assert rows[0].delivered_at is not None

    # Header sanity:
    assert captured["event_type"] == "passport.generated"
    assert captured["delivery_id"].startswith("wd_")
    expected = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"), captured["body"].encode("utf-8"), hashlib.sha256
        ).hexdigest()
    )
    assert captured["sig"] == expected


@respx.mock
def test_process_one_pending_4xx_marks_failed_no_retry(cfg: Config, workspace_id: str):
    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(return_value=httpx.Response(400, text="bad"))
    assert worker.process_one_pending(config=cfg) is True
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.FAILED
    assert "400" in rows[0].last_error


@respx.mock
def test_process_one_pending_5xx_reschedules_with_backoff(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(return_value=httpx.Response(503))
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    assert worker.process_one_pending(config=cfg) is True
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.PENDING
    assert rows[0].attempts == 1
    # First-failure backoff is 1s.
    assert (rows[0].next_attempt_at - base).total_seconds() == 1.0


@respx.mock
def test_process_one_pending_5xx_then_5xx_doubles_backoff(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    """attempts=2 → 4s backoff."""
    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(return_value=httpx.Response(503))
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    worker.process_one_pending(config=cfg)
    # Bump time past the first backoff.
    later = datetime(2026, 5, 3, 12, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(deliveries, "_now", lambda: later)
    monkeypatch.setattr(worker, "_now", lambda: later)
    worker.process_one_pending(config=cfg)
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].attempts == 2
    assert (rows[0].next_attempt_at - later).total_seconds() == 4.0


@respx.mock
def test_process_one_pending_after_max_attempts_marks_exhausted(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    """6 total 5xx → exhausted + transparency event ``webhook.delivery_exhausted``."""
    from datetime import timedelta

    from smadp.transparency import journal

    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(return_value=httpx.Response(503))
    cur = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)

    def _set_now(dt: datetime) -> None:
        monkeypatch.setattr(deliveries, "_now", lambda: dt)
        monkeypatch.setattr(worker, "_now", lambda: dt)

    for _ in range(6):
        _set_now(cur)
        worker.process_one_pending(config=cfg)
        cur += timedelta(seconds=300)

    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.EXHAUSTED
    assert rows[0].attempts == 6

    # Transparency event written.
    types = [ev.event_type for ev in journal.iter_events(config=cfg)]
    assert "webhook.delivery_exhausted" in types


@respx.mock
def test_process_one_pending_network_error_treated_as_5xx(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    _enqueue_one(cfg, workspace_id)
    respx.post("https://hook/x").mock(side_effect=httpx.ConnectError("boom"))
    base = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(deliveries, "_now", lambda: base)
    monkeypatch.setattr(worker, "_now", lambda: base)
    assert worker.process_one_pending(config=cfg) is True
    rows = list(deliveries.iter_all(config=cfg))
    assert rows[0].status == DeliveryStatus.PENDING
    assert rows[0].attempts == 1
    assert "boom" in (rows[0].last_error or "")
