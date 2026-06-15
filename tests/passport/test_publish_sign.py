"""Detached BYOK verdict signing round-trips and detects tampering."""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from smadp.passport.publish_sign import sign_verdict_dict, verify_verdict_signature

_VERDICT = {
    "verdict_id": "v_2026-06-12_a__b_abcd1234",
    "evidence_level": "docs-only",
    "headline": "ok",
}


def test_sign_produces_sidecar_fields() -> None:
    key = Ed25519PrivateKey.generate()
    sidecar = sign_verdict_dict(_VERDICT, signing_key=key)
    assert sidecar["signing_strategy"] == "byok"
    assert sidecar["canonical_sha256"].startswith("sha256:")
    assert "signature_hex" in sidecar
    expected_pub = key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    ).hex()
    assert sidecar["public_key_hex"] == expected_pub


def test_verify_round_trips() -> None:
    key = Ed25519PrivateKey.generate()
    sidecar = sign_verdict_dict(_VERDICT, signing_key=key)
    assert verify_verdict_signature(_VERDICT, sidecar) is True


def test_tampered_verdict_fails_verification() -> None:
    key = Ed25519PrivateKey.generate()
    sidecar = sign_verdict_dict(_VERDICT, signing_key=key)
    tampered = dict(_VERDICT)
    tampered["headline"] = "tampered"
    assert verify_verdict_signature(tampered, sidecar) is False
