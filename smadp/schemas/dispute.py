"""Dispute schemas (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

DISPUTE_ID_RE = re.compile(r"^dsp_[0-9]{14}_[0-9a-f]{6}$")
WORKSPACE_ID_RE = re.compile(r"^ws_[A-Z0-9]{8,}$")


class DisputeStatus(StrEnum):
    TRIAGE = "triage"
    PENDING_REVIEW = "pending_review"
    RESOLVED_REEVAL = "resolved_reeval"
    RESOLVED_STANDS = "resolved_stands"
    SPAM = "spam"


class RequestedOutcome(StrEnum):
    REEVAL = "reeval"
    WITHDRAW = "withdraw"
    AMEND = "amend"


class DisputeDecision(StrEnum):
    SPAM = "spam"
    SUBSTANTIVE = "substantive"
    REEVAL = "reeval"
    STANDS = "stands"


class Dispute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    verdict_id: str
    vendor_user_id: str
    argument_md: str
    requested_outcome: RequestedOutcome
    status: DisputeStatus
    decision_rationale_md: str | None
    filed_at: datetime
    triaged_at: datetime | None
    resolved_at: datetime | None
    sla_breached_at: datetime | None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not DISPUTE_ID_RE.match(v):
            raise ValueError(f"Invalid dispute id: {v!r}")
        return v

    @field_validator("workspace_id")
    @classmethod
    def _ws(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @field_validator("argument_md")
    @classmethod
    def _arg(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("argument_md must not be empty")
        if len(v) > 16384:
            raise ValueError("argument_md must be <= 16384 chars")
        return v


__all__ = [
    "Dispute",
    "DisputeDecision",
    "DisputeStatus",
    "RequestedOutcome",
]
