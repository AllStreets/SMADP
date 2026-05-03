"""Vendor-facing schemas: claims, responses, claim evidence."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

VENDOR_CLAIM_ID_RE = re.compile(r"^vc_[A-Z0-9]{8}$")
VENDOR_RESPONSE_ID_RE = re.compile(r"^vr_[0-9]{14}_[0-9a-f]{6}$")
WORKSPACE_ID_RE = re.compile(r"^ws_[A-Z0-9]{8,}$")
AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClaimMethod(StrEnum):
    REPO = "repo"
    DNS = "dns"
    EMAIL = "email"


class ClaimStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REVOKED = "revoked"


class VendorClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    agent_id: str
    vendor_user_id: str
    method: ClaimMethod
    token: str
    status: ClaimStatus
    evidence_url: str | None
    created_at: datetime
    granted_at: datetime | None
    revoked_at: datetime | None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not VENDOR_CLAIM_ID_RE.match(v):
            raise ValueError(f"Invalid vendor claim id: {v!r}")
        return v

    @field_validator("workspace_id")
    @classmethod
    def _ws(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @field_validator("agent_id")
    @classmethod
    def _agent(cls, v: str) -> str:
        if not AGENT_ID_RE.match(v):
            raise ValueError(f"Invalid agent id: {v!r}")
        return v

    @field_validator("token")
    @classmethod
    def _token(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("token must be at least 32 chars")
        return v


class VendorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    verdict_id: str
    vendor_user_id: str
    body_md: str
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not VENDOR_RESPONSE_ID_RE.match(v):
            raise ValueError(f"Invalid vendor response id: {v!r}")
        return v

    @field_validator("body_md")
    @classmethod
    def _body(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body_md must not be empty")
        if len(v) > 8192:
            raise ValueError("body_md must be <= 8192 chars")
        return v


class RepoEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme == "https":
            return v
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return v
        raise ValueError(
            f"repo_url must be https:// (or http://localhost for dev); got {v!r}"
        )


class DnsEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = v.strip().lower().rstrip(".")
        if not DOMAIN_RE.match(v):
            raise ValueError(f"Invalid domain: {v!r}")
        return v


class EmailEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_address: str

    @field_validator("email_address")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError(f"Invalid email: {v!r}")
        return v


class TokenEvidence(BaseModel):
    """Evidence carried by the verify call for the email method."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32)


class ClaimVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    detail: str


__all__ = [
    "ClaimMethod",
    "ClaimStatus",
    "ClaimVerification",
    "DnsEvidence",
    "EmailEvidence",
    "RepoEvidence",
    "TokenEvidence",
    "VendorClaim",
    "VendorResponse",
]
