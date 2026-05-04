"""End-to-end native integration: render passport → worker delivers translated body."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import DeliveryStatus, EventType, IntegrationKind
from smadp.tenancy import keys
from smadp.tenancy import store as tenancy
from smadp.webhooks import deliveries, store, worker


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@respx.mock
def test_slack_subscription_receives_translated_block_kit(cfg: Config):
    ws = tenancy.create_workspace(name="L", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    store.create_subscription(
        workspace_id=ws.id,
        url="https://hooks.slack.com/services/abc/def",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
        integration_kind=IntegrationKind.SLACK,
        integration_config={},
    )

    captured: dict[str, object] = {}

    def _capture(req: httpx.Request) -> httpx.Response:
        captured["body"] = req.content.decode("utf-8")
        captured["sig"] = req.headers.get("X-SMADP-Signature")
        captured["event_type"] = req.headers.get("X-SMADP-Event-Type")
        captured["content_type"] = req.headers.get("Content-Type")
        return httpx.Response(200)

    respx.post("https://hooks.slack.com/services/abc/def").mock(side_effect=_capture)

    render_passport(
        verdict={
            "verdict_id": "vdt_NATIVE",
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

    # Pre-worker: delivery row pending and body is already Slack-shaped.
    rows = list(deliveries.iter_all(config=cfg))
    assert len(rows) == 1
    assert rows[0].status == DeliveryStatus.PENDING
    pre_obj = json.loads(rows[0].body)
    assert "Passport generated" in pre_obj["text"]

    assert worker.process_one_pending(config=cfg) is True
    rows_after = list(deliveries.iter_all(config=cfg))
    assert rows_after[0].status == DeliveryStatus.DELIVERED

    # Post-worker: Slack got the Block Kit body, signature header is present.
    assert captured["event_type"] == "passport.generated"
    assert captured["content_type"] == "application/json"
    assert captured["sig"].startswith("sha256=")
    obj = json.loads(captured["body"])
    assert "Passport generated for vdt_NATIVE" in obj["text"]
    assert isinstance(obj["blocks"], list)
