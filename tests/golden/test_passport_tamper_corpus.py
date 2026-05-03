"""Tampered-passport corpus — every variety must fail verification."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from smadp.passport.verify import verify_passport
from tests.fixtures.passport.build_fixture import build_fixture_passport


@pytest.fixture
def passport_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> bytes:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return build_fixture_passport(tmp_path)


def test_corpus_baseline_passes(passport_html: bytes):
    """Sanity: untouched passport verifies."""
    assert verify_passport(passport_html).valid is True


# ---------- 12 tamper varieties ---------- #


def test_tamper_1_signature_byte(passport_html: bytes):
    bad = passport_html.replace(
        b'smadp-signature-hex" content="',
        b'smadp-signature-hex" content="ff',
        1,
    )
    assert verify_passport(bad).valid is False


def test_tamper_2_public_key_swap(passport_html: bytes):
    """Replace the embedded pub key with a different valid key."""
    other = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
        .hex()
    )
    bad = re.sub(
        rb'(name="smadp-public-key-hex" content=")[0-9a-f]+(")',
        rb"\g<1>" + other.encode() + rb"\g<2>",
        passport_html,
        count=1,
    )
    assert verify_passport(bad).valid is False


def test_tamper_3_canonical_sha_meta_lies(passport_html: bytes):
    bad = re.sub(
        rb'(name="smadp-canonical-sha256" content=")sha256:[0-9a-f]+(")',
        rb"\g<1>sha256:" + b"0" * 64 + rb"\g<2>",
        passport_html,
        count=1,
    )
    assert verify_passport(bad).valid is False


def test_tamper_4_payload_verdict_id_changed(passport_html: bytes):
    bad = re.sub(
        rb'("verdict_id":")vdt_FIXTURE(")',
        rb"\g<1>vdt_HACKED\g<2>",
        passport_html,
        count=1,
    )
    assert verify_passport(bad).valid is False


def test_tamper_5_payload_score_changed(passport_html: bytes):
    bad = passport_html.replace(b'"composite_score":0.42', b'"composite_score":0.99', 1)
    assert verify_passport(bad).valid is False


def test_tamper_6_payload_framework_mapping_changed(passport_html: bytes):
    bad = passport_html.replace(b'"GOVERN-1.1"', b'"GOVERN-9.9"', 1)
    assert verify_passport(bad).valid is False


def test_tamper_7_rendered_at_changed(passport_html: bytes):
    bad = passport_html.replace(b"2026-05-03T12:00:00Z", b"2026-05-03T12:00:01Z")
    assert verify_passport(bad).valid is False


def test_tamper_8_signing_strategy_unknown(passport_html: bytes):
    bad = passport_html.replace(
        b'name="smadp-signing-strategy" content="byok"',
        b'name="smadp-signing-strategy" content="totally_invalid"',
    )
    assert verify_passport(bad).valid is False


def test_tamper_9_payload_script_removed(passport_html: bytes):
    """Strip the embedded canonical payload script tag entirely."""
    bad = re.sub(
        rb'<script type="application/json" id="smadp-passport-payload">.+?</script>',
        b"",
        passport_html,
        count=1,
        flags=re.DOTALL,
    )
    assert verify_passport(bad).valid is False


def test_tamper_10_payload_truncated(passport_html: bytes):
    """Truncate the JSON payload mid-way to force a JSONDecodeError."""
    bad = re.sub(
        rb'(<script type="application/json" id="smadp-passport-payload">)(.{20})(.+?)(</script>)',
        rb"\g<1>\g<2></script>",
        passport_html,
        count=1,
        flags=re.DOTALL,
    )
    assert verify_passport(bad).valid is False


def test_tamper_11_signature_meta_removed(passport_html: bytes):
    bad = re.sub(
        rb'<meta name="smadp-signature-hex" content="[0-9a-f]*"\s*/?>',
        b"",
        passport_html,
        count=1,
    )
    assert verify_passport(bad).valid is False


def test_tamper_12_public_key_hex_invalid(passport_html: bytes):
    bad = re.sub(
        rb'(name="smadp-public-key-hex" content=")[0-9a-f]+(")',
        rb"\g<1>not-hex\g<2>",
        passport_html,
        count=1,
    )
    assert verify_passport(bad).valid is False
