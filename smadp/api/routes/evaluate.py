"""`POST /api/evaluate` — produce verdicts for every pair of submitted agents."""

from __future__ import annotations

from itertools import combinations

from fastapi import APIRouter, HTTPException, Request

from smadp.api.models import EvaluatePairResult, EvaluateRequest, EvaluateResponse
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.utils.slug import sort_pair

router = APIRouter(tags=["evaluate"])


def _rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.rate_limiter
    if not limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    summary="Evaluate every pair from a list of agents",
)
async def evaluate(request: Request, payload: EvaluateRequest) -> EvaluateResponse:
    _rate_limit(request)
    cfg = request.app.state.config
    repo = CatalogRepo(cfg)
    chronicle = Chronicle(cfg)

    # Validate every slug exists before doing any work
    for slug in payload.agents:
        if not repo.profile_exists(slug):
            raise HTTPException(status_code=404, detail=f"unknown agent: {slug}")

    # Try the analyzer; if unavailable, return cached verdicts where they exist.
    generate_verdict = None
    try:
        from smadp.analyzer.pipeline import (
            generate_verdict as _gv,  # type: ignore[import-not-found]
        )

        generate_verdict = _gv
    except Exception:
        generate_verdict = None

    results: list[EvaluatePairResult] = []
    for raw_a, raw_b in combinations(payload.agents, 2):
        a, b = sort_pair(raw_a, raw_b)
        try:
            verdict = repo.load_verdict(a, b)
        except NotFoundError:
            if generate_verdict is None:
                results.append(
                    EvaluatePairResult(
                        pair=[a, b],
                        verdict=None,
                        error="no cached verdict and analyzer is unavailable",
                    )
                )
                continue
            try:
                verdict = await generate_verdict(  # type: ignore[misc]
                    a,
                    b,
                    profile_a=repo.load_profile(a),
                    profile_b=repo.load_profile(b),
                    evidence={},
                    config=cfg,
                )
                repo.save_verdict(verdict)
                chronicle.record(
                    "verdict.generated",
                    by="api",
                    pair=(a, b),
                    verdict_id=verdict.verdict_id,
                    details={"scenario": payload.scenario},
                )
            except Exception as exc:
                results.append(
                    EvaluatePairResult(
                        pair=[a, b],
                        verdict=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
        results.append(EvaluatePairResult(pair=[a, b], verdict=verdict.model_dump(mode="json")))

    return EvaluateResponse(pairs=results)
