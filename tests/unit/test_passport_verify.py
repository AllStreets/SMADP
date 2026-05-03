"""Tests for offline passport verification."""

from __future__ import annotations

from pathlib import Path

import pytest
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
    monkeypatch.delenv("SMADP_SIGSTORE_ENABLED", raising=False)
    return Config()


def _make_passport(cfg: Config) -> bytes:
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=ws.id, private_key=priv, config=cfg)
    return render_passport(
        verdict={
            "verdict_id": "vdt_VERIFY",
            "pair": ["a/x", "b/y"],
            "headline": "Verify test",
            "composite_score": 0.31,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
        },
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )


def test_verify_passport_accepts_unmodified(cfg: Config):
    html = _make_passport(cfg)
    result = verify_passport(html)
    assert result.valid is True
    assert result.reason is None


def test_verify_passport_rejects_when_signature_corrupted(cfg: Config):
    html = _make_passport(cfg)
    tampered = html.replace(
        b'name="smadp-signature-hex" content="', b'name="smadp-signature-hex" content="00'
    )
    result = verify_passport(tampered)
    assert result.valid is False
    assert "signature" in (result.reason or "").lower()


def test_verify_passport_rejects_unknown_signing_strategy(cfg: Config):
    html = _make_passport(cfg)
    tampered = html.replace(
        b'name="smadp-signing-strategy" content="byok"',
        b'name="smadp-signing-strategy" content="bogus"',
    )
    result = verify_passport(tampered)
    assert result.valid is False
    assert "signing_strategy" in (result.reason or "").lower()


def test_verify_passport_rejects_payload_canonical_mismatch(cfg: Config):
    """If the embedded payload's canonical sha doesn't match the meta tag, fail."""
    html = _make_passport(cfg)
    # Replace in the JSON payload specifically to cause canonical mismatch
    tampered = html.replace(b'"verdict_id":"vdt_VERIFY"', b'"verdict_id":"vdt_TAMPER"')
    result = verify_passport(tampered)
    assert result.valid is False
