"""Tests for BYOK signing strategy in smadp.passport.sign."""

from __future__ import annotations

import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.passport.canonical import canonical_passport_sha256
from smadp.passport.render import _render_unsigned
from smadp.passport.sign import inject_signature_meta, sign_unsigned_html


def _verdict():
    return {
        "verdict_id": "vdt_X",
        "headline": "Test",
        "composite_score": 0.5,
        "framework_mappings": {},
    }


def test_inject_signature_meta_replaces_empty_placeholders():
    html = _render_unsigned(
        verdict=_verdict(),
        frameworks={},
        evidence_index={},
        evidence_blobs_b64="",
        rendered_at="2026-05-03T12:00:00Z",
    )
    out = inject_signature_meta(
        html,
        signature_hex="aabb",
        public_key_hex="ccdd",
        signing_strategy_label="byok",
        rekor_uuid="",
        rekor_log_index="",
        transparency_event_id=42,
        transparency_status="local",
    ).decode("utf-8")
    assert 'name="smadp-signature-hex" content="aabb"' in out
    assert 'name="smadp-public-key-hex" content="ccdd"' in out
    assert 'name="smadp-signing-strategy" content="byok"' in out
    assert 'name="smadp-transparency-event-id" content="42"' in out


def test_sign_unsigned_html_byok_produces_verifiable_signature():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    html = _render_unsigned(
        verdict=_verdict(),
        frameworks={},
        evidence_index={},
        evidence_blobs_b64="",
        rendered_at="2026-05-03T12:00:00Z",
    )
    canonical_sha = canonical_passport_sha256(
        verdict=_verdict(),
        frameworks={},
        evidence_index={},
        rendered_at="2026-05-03T12:00:00Z",
    )
    signed = sign_unsigned_html(
        html,
        signing_key=priv,
        canonical_sha256=canonical_sha,
        signing_strategy_label="byok",
        transparency_event_id=1,
        transparency_status="local",
        rekor_uuid="",
        rekor_log_index="",
    )
    text = signed.decode("utf-8")
    sig_match = re.search(r'name="smadp-signature-hex" content="([0-9a-f]+)"', text)
    assert sig_match is not None
    sig_hex = sig_match.group(1)
    pub.verify(bytes.fromhex(sig_hex), canonical_sha.encode("utf-8"))


def test_inject_signature_meta_idempotent():
    """Calling inject twice with same values yields same bytes (no compounding)."""
    html = _render_unsigned(
        verdict=_verdict(),
        frameworks={},
        evidence_index={},
        evidence_blobs_b64="",
        rendered_at="2026-05-03T12:00:00Z",
    )
    once = inject_signature_meta(
        html,
        signature_hex="aa",
        public_key_hex="bb",
        signing_strategy_label="byok",
        rekor_uuid="",
        rekor_log_index="",
        transparency_event_id=1,
        transparency_status="local",
    )
    twice = inject_signature_meta(
        once,
        signature_hex="aa",
        public_key_hex="bb",
        signing_strategy_label="byok",
        rekor_uuid="",
        rekor_log_index="",
        transparency_event_id=1,
        transparency_status="local",
    )
    assert once == twice
