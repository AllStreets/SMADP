"""`/api/verdicts` — list and fetch verdicts."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from smadp.api.models import Page, VerdictListResponse, VerdictSummary
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.schemas import Verdict
from smadp.utils.slug import sort_pair

router = APIRouter(prefix="/verdicts", tags=["verdicts"])


_SEV_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _max_severity(verdict: Verdict) -> str:
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
    return max(sevs, key=lambda s: _SEV_RANK.get(s, 0))


def _summarize(verdict: Verdict) -> VerdictSummary:
    return VerdictSummary(
        pair=list(verdict.pair),
        verdict_id=verdict.verdict_id,
        headline=verdict.headline,
        evidence_level=verdict.evidence_level,
        composite_score=verdict.composite_score,
        confidence=verdict.confidence,
        max_severity=_max_severity(verdict),
        generated_at=verdict.generated_at,
    )


@router.get(
    "",
    response_model=VerdictListResponse,
    summary="List verdicts (filter by evidence level, minimum severity, risk)",
)
async def list_verdicts(
    request: Request,
    evidence_level: Annotated[str | None, Query(description="evidence level filter")] = None,
    min_severity: Annotated[
        str | None, Query(description="minimum severity across any sub-verdict")
    ] = None,
    risk: Annotated[
        str | None,
        Query(
            description=(
                "Risk id (A_prompt_injection, B_data_leakage, "
                "C_capability_conflict, D_cascading_error, E_compliance)"
            )
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VerdictListResponse:
    repo = CatalogRepo(request.app.state.config)
    verdicts = repo.list_verdicts(evidence_level=evidence_level)

    if min_severity is not None:
        threshold = _SEV_RANK.get(min_severity, 0)
        verdicts = [v for v in verdicts if _SEV_RANK.get(_max_severity(v), 0) >= threshold]

    if risk is not None:
        risk_filtered: list[Verdict] = []
        for v in verdicts:
            if not hasattr(v.sub_verdicts, risk):
                continue
            sv = getattr(v.sub_verdicts, risk)
            if _SEV_RANK.get(sv.severity, 0) >= _SEV_RANK.get(min_severity or "low", 1):
                risk_filtered.append(v)
        verdicts = risk_filtered

    total = len(verdicts)
    page = verdicts[offset : offset + limit]
    return VerdictListResponse(
        items=[_summarize(v) for v in page],
        page=Page(total=total, limit=limit, offset=offset),
    )


@router.get(
    "/{a}/{b}",
    summary="Fetch a single verdict (the pair is alphabetized for you)",
)
async def get_verdict(request: Request, a: str, b: str) -> dict[str, Any]:
    repo = CatalogRepo(request.app.state.config)
    try:
        slug_a, slug_b = sort_pair(a, b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        verdict = repo.load_verdict(slug_a, slug_b)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return verdict.model_dump(mode="json")
