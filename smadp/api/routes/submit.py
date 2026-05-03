"""`POST /api/agents` — submit an agent for unverified profiling, plus `/api/jobs/{id}`."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from smadp.api.models import JobStatus, SubmitAgentRequest
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo
from smadp.utils.slug import normalize_slug

router = APIRouter(tags=["submit"])


def _rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.rate_limiter
    if not limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def _run_profile_job(
    job_id: str,
    payload: SubmitAgentRequest,
    request: Request,
) -> None:
    job_store = request.app.state.job_store
    cfg = request.app.state.config
    job_store.update(job_id, status="running")
    chronicle = Chronicle(cfg)
    repo = CatalogRepo(cfg)

    try:
        # Late import — profiler is built by another subagent and may not be
        # installed in every environment (e.g. minimal API-only container).
        from smadp.profiler.pipeline import build_profile  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        job_store.update(
            job_id,
            status="failed",
            error=f"profiler unavailable: {type(exc).__name__}: {exc}",
        )
        return

    try:
        slug = payload.slug or (normalize_slug(payload.name) if payload.name else None)
        urls = [str(u) for u in payload.urls]
        profile = build_profile(  # type: ignore[misc]
            urls=urls,
            name=payload.name,
            slug=slug,
            verified=False,
        )
        path = repo.save_profile(profile, verified=False)
        chronicle.record(
            "profile.created",
            by="api",
            slug=profile.slug,
            details={"path": str(path), "via": "POST /api/agents"},
        )
        job_store.update(
            job_id,
            status="succeeded",
            result={"slug": profile.slug, "path": str(path)},
        )
    except Exception as exc:  # noqa: BLE001
        job_store.update(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )


@router.post(
    "/agents",
    response_model=JobStatus,
    summary="Submit an agent for unverified profiling",
    status_code=202,
)
async def submit_agent(
    request: Request,
    payload: SubmitAgentRequest,
    background: BackgroundTasks,
) -> JobStatus:
    _rate_limit(request)
    job_id = request.app.state.job_store.create(kind="profile")
    background.add_task(_run_profile_job, job_id, payload, request)
    record = request.app.state.job_store.get(job_id)
    assert record is not None
    return JobStatus(**record)


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatus,
    summary="Poll a background job",
)
async def get_job(request: Request, job_id: str) -> JobStatus:
    record = request.app.state.job_store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown job: {job_id}")
    return JobStatus(**record)
