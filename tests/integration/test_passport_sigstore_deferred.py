"""Integration test: Sigstore unreachable -> deferred -> retry succeeds."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.passport.verify import verify_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_SIGSTORE_ENABLED", "true")
    monkeypatch.setenv("SMADP_REKOR_URL", "https://rekor.example.test")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


def _verdict():
    return {
        "verdict_id": "vdt_DEFER",
        "pair": ["a/x", "b/y"],
        "headline": "Deferred test",
        "composite_score": 0.5,
        "framework_mappings": {},
    }


@respx.mock
def test_sigstore_unreachable_renders_deferred(cfg: Config, workspace_id: str):
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(503)
    )
    html = render_passport(
        verdict=_verdict(), frameworks={}, evidence_index={}, evidence_blobs={},
        signing_strategy=SigningStrategy.SIGSTORE, workspace_id=workspace_id,
        rendered_at="2026-05-03T12:00:00Z", config=cfg,
    )
    text = html.decode("utf-8")
    assert 'name="smadp-transparency-status" content="deferred"' in text
    assert 'name="smadp-rekor-uuid" content=""' in text
    # Verifier still accepts (signature is valid; deferred is a status, not a failure)
    assert verify_passport(html).valid is True


@respx.mock
def test_sigstore_success_embeds_rekor_uuid_and_proof_index(
    cfg: Config, workspace_id: str
):
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(
            201,
            json={
                "uuid-success-001": {
                    "logIndex": 7777,
                    "logID": "x",
                    "integratedTime": 1714740000,
                }
            },
        )
    )
    respx.get(
        "https://rekor.example.test/api/v1/log/entries/uuid-success-001/proof"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "logIndex": 7777,
                "treeSize": 100000,
                "rootHash": "ab" * 32,
                "hashes": [],
                "checkpoint": "x",
            },
        )
    )
    html = render_passport(
        verdict=_verdict(), frameworks={}, evidence_index={}, evidence_blobs={},
        signing_strategy=SigningStrategy.SIGSTORE, workspace_id=workspace_id,
        rendered_at="2026-05-03T12:00:00Z", config=cfg,
    )
    text = html.decode("utf-8")
    assert 'name="smadp-transparency-status" content="submitted"' in text
    assert 'name="smadp-rekor-uuid" content="uuid-success-001"' in text
    assert 'name="smadp-rekor-log-index" content="7777"' in text
    assert verify_passport(html).valid is True
