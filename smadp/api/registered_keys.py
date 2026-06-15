"""Operator-curated registry of third-party federation signing keys.

Federated profile submissions (Pillar S3.2) must be signed by a key the
operator has registered in ``config/registered_keys.json``. A key can be
disabled without deletion (audit trail). Disabled/unknown keys and any
signature mismatch fail closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass(frozen=True)
class RegisteredKeys:
    keys: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> RegisteredKeys:
        if not path.exists():
            return cls(keys={})
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(keys={})
        return cls(keys=data if isinstance(data, dict) else {})

    def verify(self, *, key_id: str, body: bytes, signature_hex: str) -> bool:
        entry = self.keys.get(key_id)
        if not entry or not entry.get("enabled", False):
            return False
        try:
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(entry["public_key_hex"]))
            pub.verify(bytes.fromhex(signature_hex), body)
        except (KeyError, ValueError, InvalidSignature):
            return False
        return True


__all__ = ["RegisteredKeys"]
