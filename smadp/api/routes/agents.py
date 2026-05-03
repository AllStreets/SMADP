"""`/api/agents` — list profiles, fetch one, list verdicts involving one."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from smadp.api.models import (
    Page,
    ProfileListResponse,
    ProfileSummary,
    VerdictListResponse,
    VerdictSummary,
)
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.schemas import Verdict

router = APIRouter(prefix="/agents", tags=["agents"])


def _summarize_profile(profile: Any) -> ProfileSummary:
    return ProfileSummary(
        slug=profile.slug,
        name=profile.name,
        tagline=profile.tagline,
        vendor=profile.vendor.handle,
        category=profile.category,
        source_type=profile.source_type,
        verification_status=profile.verification.status,
        last_refreshed_at=profile.last_refreshed_at,
    )


def _summarize_verdict(verdict: Verdict) -> VerdictSummary:
    sevs = [
        getattr(verdict.sub_verdicts, name).severity
        for name in (
            "A_prompt_injection",
            "B_data_leakage",
            "C_capability_conflict",
            "D_cascading_error",
            "E_compliance",
        )
    ]
    rank = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    max_sev = max(sevs, key=lambda s: rank.get(s, 0))
    return VerdictSummary(
        pair=list(verdict.pair),
        verdict_id=verdict.verdict_id,
        headline=verdict.headline,
        evidence_level=verdict.evidence_level,
        composite_score=verdict.composite_score,
        confidence=verdict.confidence,
        max_severity=max_sev,
        generated_at=verdict.generated_at,
    )


@router.get(
    "",
    response_model=ProfileListResponse,
    summary="List Safety Profiles",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {
                                "slug": "claude-code",
                                "name": "Claude Code",
                                "tagline": "Anthropic's CLI",
                                "vendor": "anthropic",
                                "category": "coding",
                                "source_type": "closed-source",
                                "verification_status": "verified",
                                "last_refreshed_at": "2026-05-02T00:00:00Z",
                            }
                        ],
                        "page": {"total": 1, "limit": 50, "offset": 0},
                    }
                }
            }
        }
    },
)
async def list_agents(
    request: Request,
    category: Annotated[str | None, Query(description="Filter by category id")] = None,
    source_type: Annotated[str | None, Query(description="open-source | closed-source | source-available")] = None,
    status: Annotated[str | None, Query(description="verification status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProfileListResponse:
    repo = CatalogRepo(request.app.state.config)
    profiles = repo.list_profiles(
        status=status,  # type: ignore[arg-type]
        category=category,
        source_type=source_type,
    )
    total = len(profiles)
    page = profiles[offset : offset + limit]
    return ProfileListResponse(
        items=[_summarize_profile(p) for p in page],
        page=Page(total=total, limit=limit, offset=offset),
    )


@router.get(
    "/{slug}",
    summary="Get a single Safety Profile",
)
async def get_agent(request: Request, slug: str) -> dict[str, Any]:
    repo = CatalogRepo(request.app.state.config)
    try:
        profile = repo.load_profile(slug)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return profile.model_dump(mode="json")


@router.get(
    "/{slug}/verdicts",
    response_model=VerdictListResponse,
    summary="List verdicts that involve this agent",
)
async def list_agent_verdicts(
    request: Request,
    slug: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VerdictListResponse:
    repo = CatalogRepo(request.app.state.config)
    if not repo.profile_exists(slug):
        raise HTTPException(status_code=404, detail=f"unknown agent: {slug}")
    verdicts = repo.list_verdicts(slug=slug)
    total = len(verdicts)
    page = verdicts[offset : offset + limit]
    return VerdictListResponse(
        items=[_summarize_verdict(v) for v in page],
        page=Page(total=total, limit=limit, offset=offset),
    )
