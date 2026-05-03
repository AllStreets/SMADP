"""Tests for passport Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from smadp.schemas.passport import (
    PassportMetadata,
    PassportRenderRequest,
    SigningStrategy,
    VerificationResult,
)


def test_signing_strategy_values():
    assert SigningStrategy.SIGSTORE.value == "sigstore"
    assert SigningStrategy.BYOK.value == "byok"
    # iteration order must be stable for golden tests
    assert [s.value for s in SigningStrategy] == ["sigstore", "byok"]


def test_passport_render_request_minimal():
    req = PassportRenderRequest(
        slug_a="anthropic/claude-sonnet-4.6",
        slug_b="openai/gpt-5",
        signing_strategy=SigningStrategy.BYOK,
        workspace_id="ws_TEST0001",
    )
    assert req.signing_strategy == SigningStrategy.BYOK


def test_passport_render_request_rejects_extra():
    with pytest.raises(ValidationError):
        PassportRenderRequest(
            slug_a="a",
            slug_b="b",
            signing_strategy=SigningStrategy.BYOK,
            workspace_id="ws_X0000001",
            unexpected="boom",
        )


def test_passport_metadata_roundtrip():
    md = PassportMetadata(
        verdict_id="vdt_X",
        rendered_at="2026-05-03T12:00:00Z",
        signing_strategy=SigningStrategy.BYOK,
        signature_hex="aabb",
        public_key_hex="ccdd",
        canonical_sha256="sha256:" + "0" * 64,
        rekor_uuid=None,
        rekor_log_index=None,
        transparency_event_id=42,
        transparency_status="local",
    )
    dumped = md.model_dump(mode="json")
    rebuilt = PassportMetadata.model_validate(dumped)
    assert rebuilt == md


def test_passport_metadata_rejects_extra():
    with pytest.raises(ValidationError):
        PassportMetadata(
            verdict_id="vdt_X",
            rendered_at="2026-05-03T12:00:00Z",
            signing_strategy=SigningStrategy.BYOK,
            signature_hex="aa",
            public_key_hex="bb",
            canonical_sha256="sha256:" + "0" * 64,
            rekor_uuid=None,
            rekor_log_index=None,
            transparency_event_id=1,
            transparency_status="local",
            extra="boom",
        )


def test_verification_result_valid():
    r = VerificationResult(valid=True, reason=None)
    assert r.valid is True
    assert r.reason is None


def test_verification_result_invalid():
    r = VerificationResult(valid=False, reason="signature mismatch")
    assert r.valid is False
    assert r.reason == "signature mismatch"


def test_verification_result_rejects_extra():
    with pytest.raises(ValidationError):
        VerificationResult(valid=True, reason=None, foo="bar")
