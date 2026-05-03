"""Transparency journal schemas (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]+$")


class SignedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    event_type: str
    payload: dict[str, Any]
    ts: datetime
    prev_hash: str
    signature: str
    rekor_uuid: str | None = None

    @field_validator("prev_hash")
    @classmethod
    def _prev_hash(cls, v: str) -> str:
        if not SHA256_RE.match(v):
            raise ValueError(f"Invalid prev_hash: {v!r}")
        return v

    @field_validator("signature")
    @classmethod
    def _signature_hex(cls, v: str) -> str:
        if not HEX_RE.match(v):
            raise ValueError(f"Signature must be lowercase hex, got: {v!r}")
        return v


class InclusionProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_id: int
    log_index: int
    leaf_hash: str
    path: list[str]

    @field_validator("leaf_hash")
    @classmethod
    def _leaf_hash(cls, v: str) -> str:
        if not SHA256_RE.match(v):
            raise ValueError(f"Invalid leaf_hash: {v!r}")
        return v

    @field_validator("path")
    @classmethod
    def _path_hashes(cls, v: list[str]) -> list[str]:
        for h in v:
            if not SHA256_RE.match(h):
                raise ValueError(f"Invalid hash in path: {h!r}")
        return v


__all__ = ["InclusionProof", "SignedEvent"]
