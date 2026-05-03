"""Request/response DTOs for the SMADP REST API.

We deliberately do NOT reuse the catalog Pydantic models for request bodies.
Catalog models are strict (e.g. they require `verification` blocks the API
shouldn't accept from clients); DTOs let us evolve the wire format without
breaking the on-disk schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


# ---------------------------------------------------------------------- shared
class Problem(BaseModel):
    """RFC-7807 Problem JSON."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "https://smadp.dev/problems/not-found",
                    "title": "Not Found",
                    "status": 404,
                    "detail": "profile not found: claude-code",
                    "instance": "/api/agents/claude-code",
                }
            ]
        }
    )

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class Page(BaseModel):
    total: int
    limit: int
    offset: int


# -------------------------------------------------------------------- profiles
class ProfileSummary(BaseModel):
    """A trimmed-down profile representation for list endpoints."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "slug": "claude-code",
                    "name": "Claude Code",
                    "tagline": "Anthropic's official CLI for Claude.",
                    "vendor": "anthropic",
                    "category": "coding",
                    "source_type": "closed-source",
                    "verification_status": "verified",
                    "last_refreshed_at": "2026-05-02T00:00:00Z",
                }
            ]
        }
    )

    slug: str
    name: str
    tagline: str | None = None
    vendor: str
    category: str
    source_type: str
    verification_status: str
    last_refreshed_at: datetime


class ProfileListResponse(BaseModel):
    items: list[ProfileSummary]
    page: Page


# -------------------------------------------------------------------- verdicts
class VerdictSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "pair": ["claude-code", "cursor"],
                    "verdict_id": "v_2026-05-02_claude-code__cursor_a1b2",
                    "headline": "High-risk capability overlap on shared filesystem.",
                    "evidence_level": "docs-only",
                    "composite_score": 0.71,
                    "confidence": 0.62,
                    "max_severity": "high",
                    "generated_at": "2026-05-02T00:00:00Z",
                }
            ]
        }
    )

    pair: list[str]
    verdict_id: str
    headline: str
    evidence_level: str
    composite_score: float
    confidence: float
    max_severity: str
    generated_at: datetime


class VerdictListResponse(BaseModel):
    items: list[VerdictSummary]
    page: Page


# ---------------------------------------------------------------------- submit
class SubmitAgentRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "urls": ["https://github.com/some-org/some-agent"],
                    "name": "Some Agent",
                    "slug": "some-agent",
                }
            ]
        }
    )

    urls: list[HttpUrl] = Field(min_length=1, max_length=10)
    name: str | None = None
    slug: str | None = None


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    kind: str
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] | None = None
    error: str | None = None


# -------------------------------------------------------------------- evaluate
class EvaluateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "agents": ["claude-code", "cursor", "windsurf"],
                    "scenario": "shared-workspace",
                }
            ]
        }
    )

    agents: list[str] = Field(min_length=2, max_length=12)
    scenario: str | None = None


class EvaluatePairResult(BaseModel):
    pair: list[str]
    verdict: dict[str, Any] | None = None
    error: str | None = None


class EvaluateResponse(BaseModel):
    pairs: list[EvaluatePairResult]


# ---------------------------------------------------------------------- search
class SearchResponseItem(BaseModel):
    kind: str
    ref: str
    title: str
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    items: list[SearchResponseItem]


# ----------------------------------------------------------------- frameworks
class FrameworkControl(BaseModel):
    id: str
    name: str
    applies_to_risks: list[str]
    verdicts: list[str] = Field(default_factory=list)


class Framework(BaseModel):
    id: str
    name: str
    version: str
    url: str
    controls: list[FrameworkControl]


class FrameworksResponse(BaseModel):
    frameworks: list[Framework]


# ----------------------------------------------------------------- chronicle
class ChronicleResponseItem(BaseModel):
    ts: datetime
    event: str
    by: str
    slug: str | None = None
    pair: list[str] | None = None
    verdict_id: str | None = None
    model: str | None = None
    outcome: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ChronicleResponse(BaseModel):
    items: list[ChronicleResponseItem]
    page: Page


# ------------------------------------------------------------------ sandbox
class SandboxRunRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"agents": ["claude-code", "cursor"], "scenario": "shared-workspace"}]
        }
    )

    agents: list[str] = Field(min_length=2, max_length=2)
    scenario: str | None = None


class SandboxRunSummary(BaseModel):
    run_id: str
    pair: list[str]
    scenario: str | None
    status: str
    outcome: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SandboxRunListResponse(BaseModel):
    items: list[SandboxRunSummary]


# ------------------------------------------------------------------- health
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    schema_version: str
    rubric_version: str


class HealthDeepResponse(HealthResponse):
    checks: dict[str, dict[str, Any]]


# ---------------------------------------------------------------------- meta
class MetaJSONResponse(BaseModel):
    """Wrapper for arbitrary meta JSON payloads."""

    payload: dict[str, Any]
