"""Health check endpoints."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, Request

from smadp import __version__
from smadp.api.models import HealthDeepResponse, HealthResponse
from smadp.config import RUBRIC_VERSION, SCHEMA_VERSION, Config

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    response_model=HealthResponse,
    summary="Liveness probe",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "version": "0.1.0",
                        "schema_version": "1.0",
                        "rubric_version": "1.0",
                    }
                }
            }
        }
    },
)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        schema_version=SCHEMA_VERSION,
        rubric_version=RUBRIC_VERSION,
    )


@router.get(
    "/deep",
    response_model=HealthDeepResponse,
    summary="Deep health check (openai key, container runtime, catalog)",
)
async def health_deep(request: Request) -> HealthDeepResponse:
    cfg: Config = request.app.state.config
    checks: dict[str, dict[str, Any]] = {}

    # ---- openai key
    checks["openai_api_key"] = {
        "ok": bool(cfg.openai_api_key),
        "detail": "set" if cfg.openai_api_key else "missing",
    }

    # ---- container runtime
    container = shutil.which("podman") or shutil.which("docker")
    checks["container_runtime"] = {
        "ok": container is not None,
        "runtime": container,
    }

    # ---- catalog readability
    catalog_ok = cfg.catalog_dir.exists() and cfg.catalog_dir.is_dir()
    checks["catalog"] = {
        "ok": catalog_ok,
        "path": str(cfg.catalog_dir),
    }

    overall = "ok" if all(c["ok"] for c in checks.values()) else "degraded"
    return HealthDeepResponse(
        status=overall,  # type: ignore[arg-type]
        version=__version__,
        schema_version=SCHEMA_VERSION,
        rubric_version=RUBRIC_VERSION,
        checks=checks,
    )
