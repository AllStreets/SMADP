"""End-to-end webhook lifecycle: render passport → worker delivers signed POST."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType
from smadp.tenancy import keys, store as tenancy
from smadp.webhooks import deliveries, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@respx.mock
def test_full_lifecycle_subscribe_render_deliver(cfg: Config):
    # 1. workspace + BYOK
    ws = tenancy.create_workspace(name="L", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )

    # 2. subscribe
    sub, secret = store.create_subscription(
        workspace_id=ws.id, url="https://hook/x",
        event_types=[EventType.PASSPORT_GENERATED], config=cfg,
    )

    # 3. mock the subscriber
    captured: dict[str, str] = {}

    def _capture(req: httpx.Request) -> httpx.Response:
        captured["sig"] = req.headers["X-SMADP-Signature"]
        captured["delivery_id"] = req.headers["X-SMADP-Delivery-Id"]
        captured["event_type"] = req.headers["X-SMADP-Event-Type"]
        captured["body"] = req.content.decode("utf-8")
        return httpx.Response(200)

    respx.post("https://hook/x").mock(side_effect=_capture)

    # 4. render passport (this fires the dispatch)
    render_passport(
        verdict={
            "verdict_id": "vdt_LIFECYCLE",
            "pair": ["a/x", "b/y"],
            "headline": "L",
            "composite_score": 0.5,
            "framework_mappings": {},
        },
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )

    # 5. before worker runs, row exists pending
    rows_before = list(deliveries.iter_all(config=cfg))
    assert len(rows_before) == 1
    assert rows_before[0].status == DeliveryStatus.PENDING

    # 6. worker consumes the row
    assert worker.process_one_pending(config=cfg) is True

    rows_after = list(deliveries.iter_all(config=cfg))
    assert rows_after[0].status == DeliveryStatus.DELIVERED
    assert rows_after[0].delivered_at is not None

    # 7. signature matches
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), captured["body"].encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert captured["sig"] == expected
    assert captured["event_type"] == "passport.generated"
    assert captured["delivery_id"].startswith("wd_")
    # Body contains the verdict id and transparency_log_id binding
    assert "vdt_LIFECYCLE" in captured["body"]
    assert '"transparency_log_id":' in captured["body"]
