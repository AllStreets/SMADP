"""Passport schemas: render request, signing strategy, verification result, metadata."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SigningStrategy(StrEnum):
    SIGSTORE = "sigstore"
    BYOK = "byok"


class PassportRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug_a: str
    slug_b: str
    signing_strategy: SigningStrategy
    workspace_id: str


class PassportMetadata(BaseModel):
    """Authoritative metadata embedded in <meta> tags of a rendered passport."""

    model_config = ConfigDict(extra="forbid")

    verdict_id: str
    rendered_at: str  # ISO-8601 UTC, second-precision, ends in 'Z'
    signing_strategy: SigningStrategy
    signature_hex: str
    public_key_hex: str
    canonical_sha256: str  # "sha256:<64hex>" of the canonical payload bytes
    rekor_uuid: str | None
    rekor_log_index: int | None
    transparency_event_id: int
    transparency_status: Literal["local", "deferred", "submitted"]


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    reason: str | None


__all__ = [
    "PassportMetadata",
    "PassportRenderRequest",
    "SigningStrategy",
    "VerificationResult",
]
