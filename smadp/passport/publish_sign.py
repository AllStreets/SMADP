"""Detached Ed25519 signing of published verdicts (Pillar S3.2).

To sign a verdict at ``pending approve`` without changing the verdict's
canonical bytes (which the passport hashes — adding a signature field would be
circular), we emit a detached sidecar: a signature over the verdict's canonical
sha256. The sidecar lives at ``catalog/verdicts/<key>.sig.json`` and is rendered
on the site with verification instructions.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _canonical_sha(verdict: dict[str, Any]) -> str:
    canonical = json.dumps(
        verdict, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def sign_verdict_dict(verdict: dict[str, Any], *, signing_key: Ed25519PrivateKey) -> dict[str, Any]:
    sha = _canonical_sha(verdict)
    sig = signing_key.sign(sha.encode("utf-8"))
    pub = signing_key.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    return {
        "signing_strategy": "byok",
        "canonical_sha256": sha,
        "signature_hex": sig.hex(),
        "public_key_hex": pub.hex(),
    }


def verify_verdict_signature(verdict: dict[str, Any], sidecar: dict[str, Any]) -> bool:
    if _canonical_sha(verdict) != sidecar.get("canonical_sha256"):
        return False
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(sidecar["public_key_hex"]))
        pub.verify(
            bytes.fromhex(sidecar["signature_hex"]),
            sidecar["canonical_sha256"].encode("utf-8"),
        )
    except (KeyError, ValueError, InvalidSignature):
        return False
    return True


__all__ = ["sign_verdict_dict", "verify_verdict_signature"]
