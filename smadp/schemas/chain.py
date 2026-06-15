"""Chain schema — multi-agent (3+) compositions."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from smadp.schemas.evidence_level import EvidenceLevel
from smadp.schemas.profile import EVIDENCE_REF_RE, SLUG_RE

CHAIN_ID_RE = re.compile(r"^c_[a-z0-9-]{3,80}$")

Topology = Literal["linear", "star", "loop", "tree", "dag"]
ChannelKind = Literal["prompt", "tool-call", "shared-memory", "filesystem", "message-bus"]
Role = Literal[
    "planner",
    "executor",
    "critic",
    "retriever",
    "reasoner",
    "writer",
    "router",
    "tool",
    "judge",
    "memory",
]
Severity = Literal["none", "low", "medium", "high", "critical"]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_field: str | None = None
    evidence_ref: str | None = None
    quote: str | None = None


class SubVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    rationale: str = Field(min_length=1, max_length=600)
    citations: list[Citation] = Field(min_length=1)
    conditions: list[str] = Field(default_factory=list)
    mitigations: list[str] = Field(default_factory=list, max_length=5)


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    role: Role
    notes: str | None = Field(default=None, max_length=240)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError(f"Invalid slug: {v!r}")
        return v


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    channel: ChannelKind
    carries: list[str] = Field(default_factory=list)

    @field_validator("from_", "to")
    @classmethod
    def _validate_endpoint(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError(f"Invalid endpoint slug: {v!r}")
        return v


class SubVerdicts(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    A_prompt_injection: SubVerdict
    B_data_leakage: SubVerdict
    C_capability_conflict: SubVerdict
    D_cascading_error: SubVerdict
    E_compliance: SubVerdict


# EvidenceLevel imported from smadp.schemas.evidence_level (canonical ladder).


class Chain(BaseModel):
    """Authoritative model for `catalog/chains/<chain_id>.json`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1"] = "1.1"
    chain_id: str
    name: str = Field(min_length=1, max_length=120)
    tagline: str | None = Field(default=None, max_length=240)
    # Optional metadata added when chains became first-class
    # (authored examples + builder submissions). All optional so older
    # fixtures from before the v2 rework still validate.
    author: str | None = Field(default=None, max_length=120)
    topology: Topology
    participants: list[Participant] = Field(min_length=3, max_length=8)
    edges: list[Edge] = Field(default_factory=list)
    headline: str = Field(min_length=1, max_length=240)
    sub_verdicts: SubVerdicts
    composite_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_severity: Severity | None = None
    evidence_level: EvidenceLevel | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    framework_mappings: dict[str, list[str]] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    first_seen_at: datetime
    last_refreshed_at: datetime
    # Composition provenance (schema 1.1, additive). Records which pairwise
    # verdicts a composed chain candidate was derived from for reproducibility.
    composition_method: str | None = Field(default=None, max_length=60)
    composed_from: list[str] = Field(default_factory=list)
    stale_reason: Literal["capability_drift"] | None = None

    @field_validator("chain_id")
    @classmethod
    def _validate_chain_id(cls, v: str) -> str:
        if not CHAIN_ID_RE.match(v):
            raise ValueError(f"Invalid chain_id: {v!r}")
        return v

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, v: list[str]) -> list[str]:
        for ref in v:
            if not EVIDENCE_REF_RE.match(ref):
                raise ValueError(f"Invalid evidence ref: {ref!r}")
        return v
