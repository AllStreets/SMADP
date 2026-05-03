"""Content-addressed hashing for evidence and reproducibility."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(data: str) -> str:
    return sha256_bytes(data.encode("utf-8"))


def sha256_canonical_json(obj: Any) -> str:
    """Hash a JSON-serializable object after canonicalization (sorted keys, no spaces)."""
    canonical = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return sha256_text(canonical)
