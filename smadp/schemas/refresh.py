"""Refresh subsystem schemas: RefreshTrigger enum + queue/state models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RefreshTrigger(StrEnum):
    """Why a verdict pair was queued for re-evaluation."""

    MANUAL = "manual"
    TTL = "ttl"
    DISPUTE = "dispute"
    REPO_RELEASE = "repo_release"
    DEPENDENCY_CVE = "dependency_cve"
    MODEL_BUMP = "model_bump"
    FRAMEWORK_VERSION = "framework_version"
    SCORING_WEIGHTS = "scoring_weights"
    AGENT_CARD = "agent_card"


class RefreshQueueItem(BaseModel):
    """One row in the refresh_queue table."""

    model_config = ConfigDict(extra="forbid")

    id: int
    verdict_id: str
    trigger: RefreshTrigger
    trigger_detail: dict[str, Any] = Field(default_factory=dict)
    enqueued_at: datetime
    claimed_at: datetime | None
    done_at: datetime | None


class RefreshState(BaseModel):
    """Per-verdict refresh state, stored in the refresh_state table."""

    model_config = ConfigDict(extra="forbid")

    verdict_id: str
    last_trigger: RefreshTrigger
    last_evaluated_at: datetime
    evaluation_count: int = Field(ge=0)


__all__ = ["RefreshQueueItem", "RefreshState", "RefreshTrigger"]
