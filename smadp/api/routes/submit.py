"""`POST /api/agents` — submit an agent for unverified profiling, plus `/api/jobs/{id}`."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from smadp.api.auth import require_operator_token
from smadp.api.models import JobStatus, SubmitAgentRequest
from smadp.api.registered_keys import RegisteredKeys
from smadp.autopilot.bootstrap import _atomic_write
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo
from smadp.schemas.profile import Profile
from smadp.utils.slug import normalize_slug

router = APIRouter(tags=["submit"])

_FEDERATION_KILL_SWITCH = "FEDERATION_DISABLED"


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
    except Exception as exc:
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
    except Exception as exc:
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
    dependencies=[Depends(require_operator_token)],
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


@router.post(
    "/submit/profile",
    summary="Submit a third-party signed profile into the federation staging area",
    status_code=202,
    dependencies=[Depends(require_operator_token)],
)
async def submit_profile(request: Request) -> dict[str, Any]:
    """Accept a registered-key-signed third-party profile into ``_unverified/``.

    Operator-token-gated AND key-signature-gated. The profile lands in
    ``catalog/profiles/_unverified/`` exactly like an ONEXUS sync seed — it
    never writes a published ``profiles/<slug>.json``; the operator gate
    promotes it later. Kill switch: ``state/FEDERATION_DISABLED``.
    """
    cfg = request.app.state.config

    if (cfg.repo_root / "state" / _FEDERATION_KILL_SWITCH).exists():
        raise HTTPException(
            status_code=503,
            detail="federated submissions disabled (state/FEDERATION_DISABLED present)",
        )

    _rate_limit(request)

    body = await request.body()
    key_id = request.headers.get("X-SMADP-Key-Id", "")
    signature_hex = request.headers.get("X-SMADP-Signature", "")

    registry = RegisteredKeys.load(cfg.repo_root / "config" / "registered_keys.json")
    if not registry.verify(key_id=key_id, body=body, signature_hex=signature_hex):
        raise HTTPException(status_code=403, detail="invalid or unregistered signing key")

    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="profile must be a JSON object")

    # A submitter may not self-assert a higher rung; stamp provenance.
    raw["evidence_level"] = "unverified-profile"
    onexus = raw.get("onexus") if isinstance(raw.get("onexus"), dict) else {}
    onexus = dict(onexus)
    onexus["federated"] = {"key_id": key_id, "source": "federated-submission"}
    raw["onexus"] = onexus

    try:
        profile = Profile.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"profile failed validation: {exc}") from exc

    slug = normalize_slug(profile.slug)
    if (cfg.profiles_dir / f"{slug}.json").exists():
        raise HTTPException(status_code=409, detail=f"slug already published: {slug}")

    staged = cfg.unverified_profiles_dir / f"{slug}.json"
    _atomic_write(staged, profile.model_dump(mode="json", exclude_none=True))

    Chronicle(cfg).record(
        "profile.created",
        by="api",
        slug=slug,
        details={"path": str(staged), "via": "POST /api/submit/profile", "key_id": key_id},
    )
    return {"slug": slug, "staged": str(staged), "evidence_level": "unverified-profile"}


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
