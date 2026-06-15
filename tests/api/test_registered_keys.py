"""Registered-key store verifies signatures and fails closed on unknown/disabled keys."""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from smadp.api.registered_keys import RegisteredKeys


def _write_registry(path: Path, entries: dict) -> None:
    path.write_text(json.dumps(entries), encoding="utf-8")


def _pub_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    ).hex()


def test_valid_signature_from_enabled_key_verifies(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    body = b'{"slug":"acme"}'
    sig = key.sign(body).hex()
    reg_path = tmp_path / "registered_keys.json"
    _write_registry(reg_path, {"k1": {"enabled": True, "public_key_hex": _pub_hex(key)}})
    reg = RegisteredKeys.load(reg_path)
    assert reg.verify(key_id="k1", body=body, signature_hex=sig) is True


def test_unknown_key_fails(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    body = b"x"
    sig = key.sign(body).hex()
    reg_path = tmp_path / "registered_keys.json"
    _write_registry(reg_path, {})
    reg = RegisteredKeys.load(reg_path)
    assert reg.verify(key_id="nope", body=body, signature_hex=sig) is False


def test_disabled_key_fails(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    body = b"x"
    sig = key.sign(body).hex()
    reg_path = tmp_path / "registered_keys.json"
    _write_registry(reg_path, {"k1": {"enabled": False, "public_key_hex": _pub_hex(key)}})
    reg = RegisteredKeys.load(reg_path)
    assert reg.verify(key_id="k1", body=body, signature_hex=sig) is False


def test_bad_signature_fails(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    body = b"x"
    sig = other.sign(body).hex()  # signed with the wrong key
    reg_path = tmp_path / "registered_keys.json"
    _write_registry(reg_path, {"k1": {"enabled": True, "public_key_hex": _pub_hex(key)}})
    reg = RegisteredKeys.load(reg_path)
    assert reg.verify(key_id="k1", body=body, signature_hex=sig) is False


def test_missing_registry_is_empty(tmp_path: Path) -> None:
    reg = RegisteredKeys.load(tmp_path / "does-not-exist.json")
    assert reg.verify(key_id="k1", body=b"x", signature_hex="00") is False
