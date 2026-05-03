"""Pairwise Verdict schema (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EVIDENCE_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
VERDICT_ID_RE = re.compile(
    r"^v_\d{4}-\d{2}-\d{2}_[a-z0-9-]+__[a-z0-9-]+_[a-f0-9]{4,8}$"
)

Severity = Literal["none", "low", "medium", "high", "critical"]
EvidenceLevel = Literal["unverified-profile", "docs-only", "profile-verified", "sandbox-validated"]
SandboxOutcome = Literal["pass", "fail", "inconclusive", "errored"]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_field: str | None = None
    evidence_ref: str | None = None
    quote: str | None = None

    @field_validator("evidence_ref")
    @classmethod
    def _validate_evidence_ref(cls, v: str | None) -> str | None:
        if v is not None and not EVIDENCE_REF_RE.match(v):
            raise ValueError(f"Invalid evidence ref: {v!r}")
        return v

    @model_validator(mode="after")
    def _at_least_one(self) -> Citation:
        if not self.profile_field and not self.evidence_ref and not self.quote:
            raise ValueError("Citation must have at least one of profile_field, evidence_ref, or quote")
        return self


class SubVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    rationale: str = Field(min_length=1, max_length=600)
    citations: list[Citation] = Field(min_length=1)
    conditions: list[str] = Field(default_factory=list)
    mitigations: list[str] = Field(default_factory=list, max_length=5)


class VerdictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    id: str
    rubric_version: str


class Reproducibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rubric_url: str
    profile_a_hash: str
    profile_b_hash: str
    evidence_bundle_hash: str

    @field_validator("profile_a_hash", "profile_b_hash", "evidence_bundle_hash")
    @classmethod
    def _validate_hash(cls, v: str) -> str:
        if not EVIDENCE_REF_RE.match(v):
            raise ValueError(f"Invalid hash: {v!r}")
        return v


class SandboxRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    outcome: SandboxOutcome
    transcript_ref: str
    scenario: str | None = None


class SubVerdicts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    A_prompt_injection: SubVerdict
    B_data_leakage: SubVerdict
    C_capability_conflict: SubVerdict
    D_cascading_error: SubVerdict
    E_compliance: SubVerdict


class Verdict(BaseModel):
    """Authoritative model for `catalog/verdicts/<a>__<b>.json`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    pair: tuple[str, str]
    verdict_id: str
    generated_at: datetime
    model: VerdictModel
    evidence_level: EvidenceLevel
    confidence: float = Field(ge=0.0, le=1.0)
    composite_score: float = Field(ge=0.0, le=1.0)
    headline: str = Field(min_length=1, max_length=240)
    sub_verdicts: SubVerdicts
    framework_mappings: dict[str, list[str]] = Field(default_factory=dict)
    reproducibility: Reproducibility
    sandbox_runs: list[SandboxRun] = Field(default_factory=list)

    @field_validator("pair")
    @classmethod
    def _validate_pair(cls, v: tuple[str, str]) -> tuple[str, str]:
        a, b = v
        for slug in (a, b):
            if not SLUG_RE.match(slug):
                raise ValueError(f"Invalid slug in pair: {slug!r}")
        if a == b:
            raise ValueError("Pair must be two different slugs")
        if a > b:
            raise ValueError(f"Pair must be alphabetized; got ({a!r}, {b!r})")
        return v

    @field_validator("verdict_id")
    @classmethod
    def _validate_verdict_id(cls, v: str) -> str:
        if not VERDICT_ID_RE.match(v):
            raise ValueError(f"Invalid verdict_id: {v!r}")
        return v
