"""BYOK signing-key storage with AES-GCM at-rest encryption.

The DEK is the per-workspace AES-GCM key, derived from the deployment-wide
master KEK (env var ``SMADP_KEK_MASTER``, 64 hex chars = 32 bytes) plus the
workspace id as salt via HKDF-SHA256.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from typing import Final

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from smadp.config import Config, load_config
from smadp.tenancy.store import _connect, _ensure_schema, _transaction
from smadp.utils.time import utcnow

log = structlog.get_logger(__name__)

KEK_ENV: Final[str] = "SMADP_KEK_MASTER"

_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS signing_keys (
    workspace_id TEXT PRIMARY KEY,
    algorithm TEXT NOT NULL CHECK(algorithm = 'ed25519'),
    public_key BLOB NOT NULL,
    nonce BLOB NOT NULL,
    private_key_encrypted BLOB NOT NULL,
    created_at TEXT NOT NULL,
    rotated_from TEXT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
"""


def _ensure_keys_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


def _master_kek() -> bytes:
    raw = os.environ.get(KEK_ENV)
    if not raw:
        raise RuntimeError(f"{KEK_ENV} is not set; cannot encrypt/decrypt BYOK signing keys.")
    if len(raw) != 64:
        raise RuntimeError(f"{KEK_ENV} must be 64 hex chars (32 bytes), got {len(raw)} chars.")
    try:
        return bytes.fromhex(raw)
    except ValueError as e:
        raise RuntimeError(f"{KEK_ENV} is not valid hex: {e}") from e


def _derive_dek(workspace_id: str) -> bytes:
    """HKDF(master KEK, salt=workspace_id) -> 32-byte AES-GCM key."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=workspace_id.encode("utf-8"),
        info=b"smadp/byok/v1",
    ).derive(_master_kek())


def _encrypt(
    plaintext: bytes, *, workspace_id: str, config: Config | None = None
) -> tuple[bytes, bytes]:
    dek = _derive_dek(workspace_id)
    aes = AESGCM(dek)
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext, associated_data=workspace_id.encode("utf-8"))
    return nonce, ct


def _decrypt(
    *, nonce: bytes, ciphertext: bytes, workspace_id: str, config: Config | None = None
) -> bytes:
    dek = _derive_dek(workspace_id)
    aes = AESGCM(dek)
    return aes.decrypt(nonce, ciphertext, associated_data=workspace_id.encode("utf-8"))


def upload_signing_key(
    *,
    workspace_id: str,
    private_key: Ed25519PrivateKey,
    config: Config | None = None,
) -> None:
    cfg = config or load_config()
    priv_bytes = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    pub_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    nonce, encrypted = _encrypt(priv_bytes, workspace_id=workspace_id, config=cfg)
    now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        with _transaction(conn):
            conn.execute(
                "INSERT INTO signing_keys"
                "(workspace_id, algorithm, public_key, nonce, "
                " private_key_encrypted, created_at, rotated_from) "
                "VALUES (?, 'ed25519', ?, ?, ?, ?, NULL)",
                (workspace_id, pub_bytes, nonce, encrypted, now_iso),
            )
        log.info("tenancy.byok.uploaded", workspace_id=workspace_id)
    finally:
        conn.close()


def load_signing_key(
    *, workspace_id: str, config: Config | None = None
) -> Ed25519PrivateKey | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        cur = conn.execute(
            "SELECT nonce, private_key_encrypted FROM signing_keys WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        priv_bytes = _decrypt(
            nonce=row["nonce"],
            ciphertext=row["private_key_encrypted"],
            workspace_id=workspace_id,
            config=cfg,
        )
        return Ed25519PrivateKey.from_private_bytes(priv_bytes)
    finally:
        conn.close()


def rotate_signing_key(
    *,
    workspace_id: str,
    new_private_key: Ed25519PrivateKey,
    config: Config | None = None,
) -> None:
    """Replace the workspace's signing key, retaining the old public key id."""
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        cur = conn.execute(
            "SELECT public_key FROM signing_keys WHERE workspace_id = ?",
            (workspace_id,),
        )
        existing = cur.fetchone()
        old_pub_hex = existing["public_key"].hex() if existing else None
        priv_bytes = new_private_key.private_bytes(
            encoding=Encoding.Raw,
            format=PrivateFormat.Raw,
            encryption_algorithm=NoEncryption(),
        )
        pub_bytes = new_private_key.public_key().public_bytes(
            encoding=Encoding.Raw, format=PublicFormat.Raw
        )
        nonce, encrypted = _encrypt(priv_bytes, workspace_id=workspace_id, config=cfg)
        now_iso = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
        with _transaction(conn):
            conn.execute(
                "INSERT INTO signing_keys"
                "(workspace_id, algorithm, public_key, nonce, "
                " private_key_encrypted, created_at, rotated_from) "
                "VALUES (?, 'ed25519', ?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace_id) DO UPDATE SET "
                " public_key = excluded.public_key,"
                " nonce = excluded.nonce,"
                " private_key_encrypted = excluded.private_key_encrypted,"
                " created_at = excluded.created_at,"
                " rotated_from = excluded.rotated_from",
                (workspace_id, pub_bytes, nonce, encrypted, now_iso, old_pub_hex),
            )
        log.info("tenancy.byok.rotated", workspace_id=workspace_id)
    finally:
        conn.close()


def get_rotated_from(*, workspace_id: str, config: Config | None = None) -> str | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        cur = conn.execute(
            "SELECT rotated_from FROM signing_keys WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        return row["rotated_from"] if row else None
    finally:
        conn.close()


def get_public_key(*, workspace_id: str, config: Config | None = None) -> Ed25519PublicKey | None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        _ensure_keys_schema(conn)
        cur = conn.execute(
            "SELECT public_key FROM signing_keys WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return Ed25519PublicKey.from_public_bytes(row["public_key"])
    finally:
        conn.close()


__all__ = [
    "KEK_ENV",
    "get_public_key",
    "get_rotated_from",
    "load_signing_key",
    "rotate_signing_key",
    "upload_signing_key",
]
