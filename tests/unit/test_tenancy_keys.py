"""Tests for BYOK signing-key storage with AES-GCM at-rest encryption."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)  # 32 hex bytes for tests
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    return store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg).id


def test_upload_and_load_byok_key(cfg: Config, workspace_id: str):
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(
        workspace_id=workspace_id, private_key=priv, config=cfg
    )
    loaded = keys.load_signing_key(workspace_id=workspace_id, config=cfg)
    assert loaded is not None
    # Ed25519 signatures are deterministic; same key + same message = same sig.
    msg = b"hello transparency"
    assert priv.sign(msg) == loaded.sign(msg)


def test_load_missing_key_returns_none(cfg: Config, workspace_id: str):
    assert keys.load_signing_key(workspace_id=workspace_id, config=cfg) is None


def test_aes_gcm_round_trip_with_kek(cfg: Config, workspace_id: str):
    plaintext = b"secret payload"
    nonce, ciphertext = keys._encrypt(plaintext, workspace_id=workspace_id, config=cfg)
    assert ciphertext != plaintext
    recovered = keys._decrypt(
        nonce=nonce, ciphertext=ciphertext, workspace_id=workspace_id, config=cfg
    )
    assert recovered == plaintext


def test_corrupted_ciphertext_fails(cfg: Config, workspace_id: str):
    plaintext = b"x"
    nonce, ciphertext = keys._encrypt(plaintext, workspace_id=workspace_id, config=cfg)
    bad = bytes([ciphertext[0] ^ 0xFF]) + ciphertext[1:]
    with pytest.raises(Exception):  # InvalidTag from cryptography
        keys._decrypt(
            nonce=nonce, ciphertext=bad, workspace_id=workspace_id, config=cfg
        )


def test_kek_master_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("SMADP_KEK_MASTER", raising=False)
    cfg = Config()
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    priv = Ed25519PrivateKey.generate()
    with pytest.raises(RuntimeError, match="SMADP_KEK_MASTER"):
        keys.upload_signing_key(workspace_id=ws.id, private_key=priv, config=cfg)


def test_rotate_key_preserves_old_pub(cfg: Config, workspace_id: str):
    old = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=workspace_id, private_key=old, config=cfg)
    new = Ed25519PrivateKey.generate()
    keys.rotate_signing_key(workspace_id=workspace_id, new_private_key=new, config=cfg)
    loaded = keys.load_signing_key(workspace_id=workspace_id, config=cfg)
    assert loaded is not None
    assert loaded.sign(b"x") == new.sign(b"x")
    # rotated_from is preserved for verification of historical passports.
    rotated_from = keys.get_rotated_from(workspace_id=workspace_id, config=cfg)
    assert rotated_from is not None
