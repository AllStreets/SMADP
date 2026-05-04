"""Chronicle event schema (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChronicleEventType = Literal[
    "profile.created",
    "profile.refreshed",
    "profile.verified",
    "profile.invalidated",
    "evidence.added",
    "verdict.generated",
    "verdict.regenerated",
    "verdict.corrected",
    "sandbox.run.started",
    "sandbox.run.completed",
    "schema.migrated",
    "framework.added",
    "chain.created",
    "chain.deleted",
]


class ChronicleEvent(BaseModel):
    """One line of `catalog/_chronicle/YYYY-MM-DD.jsonl`."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    event: ChronicleEventType
    by: str
    slug: str | None = None
    pair: tuple[str, str] | None = None
    verdict_id: str | None = None
    model: str | None = None
    outcome: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
