"""Pairwise Verdict schema (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EVIDENCE_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
VERDICT_ID_RE = re.compile(r"^v_\d{4}-\d{2}-\d{2}_[a-z0-9-]+__[a-z0-9-]+_[a-f0-9]{4,8}$")

Severity = Literal["none", "low", "medium", "high", "critical"]
StaleReason = Literal["capability_drift"]
EvidenceLevel = Literal["unverified-profile", "docs-only", "profile-verified", "sandbox-validated"]
SandboxOutcome = Literal[
    "pass",
    "fail",
    "inconclusive",
    "errored",
    "halted_by_tripwire",
    "halted_by_operator",
]


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
            raise ValueError(
                "Citation must have at least one of profile_field, evidence_ref, or quote"
            )
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
    mode: Literal["cooperative", "adversarial"] = "cooperative"
    tripwire_rule: str | None = None


class SubVerdicts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    A_prompt_injection: SubVerdict
    B_data_leakage: SubVerdict
    C_capability_conflict: SubVerdict
    D_cascading_error: SubVerdict
    E_compliance: SubVerdict


class Verdict(BaseModel):
    """Authoritative model for ``catalog/verdicts/<slug1>__...__<slugN>.json``.

    Historically this held a strict 2-agent ``pair`` field. The N-ary
    generalization (Autopilot Task 3) introduces ``participants`` — the
    canonical list of 2-4 alphabetized slugs. ``pair`` is retained as a
    legacy convenience for length-2 verdicts so existing call sites that
    read ``verdict.pair[0]`` continue to work; it is auto-derived from
    (and auto-syncs to) ``participants``. For N >= 3, ``pair`` is ``None``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    # Legacy 2-agent field. New code should read ``participants`` instead.
    pair: tuple[str, str] | None = None
    # Canonical N-ary participant slug list (length 2-4, alphabetized).
    participants: list[str] = Field(default_factory=list)
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
    stale_reason: StaleReason | None = None

    @field_validator("pair")
    @classmethod
    def _validate_pair(cls, v: tuple[str, str] | None) -> tuple[str, str] | None:
        if v is None:
            return None
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

    @model_validator(mode="after")
    def _sync_participants_and_pair(self) -> Verdict:
        """Cross-validate the legacy ``pair`` field with N-ary ``participants``.

        Compatibility rules:
        * If ``participants`` is empty but ``pair`` is set → derive participants
          from pair (legacy verdict files).
        * If ``participants`` is set with length 2 and ``pair`` is None → derive
          pair from participants (so old call sites still work).
        * If both are set, they must agree (same alphabetized 2-tuple).
        * ``participants`` must be a unique alphabetized list of 2-4 slugs.
        """
        # 1) Bring participants up from legacy pair if needed.
        if not self.participants and self.pair is not None:
            self.participants = list(self.pair)

        # 2) Length check.
        n = len(self.participants)
        if not (2 <= n <= 4):
            raise ValueError(f"Verdict requires participants (list of 2-4 slugs); got {n}")

        # 3) Per-slug validation.
        for slug in self.participants:
            if not SLUG_RE.match(slug):
                raise ValueError(f"Invalid slug in participants: {slug!r}")
        if len(set(self.participants)) != n:
            raise ValueError(f"participants must be unique slugs; got {self.participants}")
        if list(self.participants) != sorted(self.participants):
            raise ValueError(f"participants must be alphabetized; got {self.participants}")

        # 4) Sync pair for length-2 verdicts (legacy compat).
        if n == 2:
            derived = (self.participants[0], self.participants[1])
            if self.pair is None:
                self.pair = derived
            elif tuple(self.pair) != derived:
                raise ValueError(
                    f"pair {self.pair!r} disagrees with participants {self.participants!r}"
                )
        else:
            # N >= 3: pair is not meaningful; reject if a caller tried to set it.
            if self.pair is not None:
                raise ValueError(
                    "pair must be None for N-ary verdicts (3+ participants); "
                    f"got pair={self.pair!r}, participants={self.participants!r}"
                )

        return self
