"""FastAPI application factory.

`create_app(config)` builds and returns the FastAPI instance with:
- CORS (open in dev; configurable later)
- Structured request logging via structlog
- RFC-7807 problem-detail error responses
- An in-memory token-bucket rate limiter on write endpoints
- All routers mounted from `smadp.api.routes`
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from smadp import __version__
from smadp.api.models import Problem
from smadp.config import RUBRIC_VERSION, SCHEMA_VERSION, Config, load_config

logger = structlog.get_logger("smadp.api")


# ---------------------------------------------------------------- rate limiter
class TokenBucket:
    """Simple per-IP sliding-window limiter for write endpoints."""

    def __init__(self, *, capacity: int = 60, window_seconds: float = 60.0) -> None:
        self.capacity = capacity
        self.window = window_seconds
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._calls[key]
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.capacity:
            return False
        bucket.append(now)
        return True


# ----------------------------------------------------------------- job store
class JobStore:
    """In-memory job tracker for background submission tasks.

    Production deployments should swap this for a durable store (SQLite/Redis).
    For v1, in-memory is sufficient because submissions are processed
    on-demand and clients poll within seconds.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, kind: str) -> str:
        job_id = uuid.uuid4().hex
        from smadp.utils.time import utcnow

        ts = utcnow()
        self._jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "kind": kind,
            "created_at": ts,
            "updated_at": ts,
            "result": None,
            "error": None,
        }
        return job_id

    def update(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        from smadp.utils.time import utcnow

        record = self._jobs.get(job_id)
        if record is None:
            return
        record["status"] = status
        if result is not None:
            record["result"] = result
        if error is not None:
            record["error"] = error
        record["updated_at"] = utcnow()

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)


# ----------------------------------------------------------------- app factory
def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or load_config()

    app = FastAPI(
        title="SMADP API",
        version=__version__,
        description=(
            "SMADP — Safe Multi-Agent Deployment Platform.\n\n"
            "Auditable, evidence-cited verdicts on whether AI agents can "
            "safely run together. This API exposes the public catalog "
            "(profiles + pairwise verdicts), full-text search, framework "
            "control mappings, the chronicle audit log, and sandbox runs."
        ),
        contact={"name": "SMADP", "url": "https://github.com/AllStreets/SMADP"},
        license_info={"name": "Apache-2.0"},
    )

    # ------------------------------------------------------------- app state
    app.state.config = cfg
    app.state.rate_limiter = TokenBucket(capacity=60, window_seconds=60.0)
    app.state.job_store = JobStore()

    # -------------------------------------------------------------------- cors
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------- request logging
    @app.middleware("http")
    async def _log_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request.error",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error=str(exc),
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        response.headers["x-request-id"] = request_id
        logger.info(
            "request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=round(elapsed_ms, 2),
        )
        return response

    # ---------------------------------------------------- problem-json errors
    @app.exception_handler(HTTPException)
    async def _http_exc(_req: Request, exc: HTTPException) -> JSONResponse:
        problem = Problem(
            type="https://smadp.dev/problems/http-error",
            title=_status_title(exc.status_code),
            status=exc.status_code,
            detail=str(exc.detail) if exc.detail is not None else None,
            instance=str(_req.url.path),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=problem.model_dump(exclude_none=True),
            media_type="application/problem+json",
        )

    @app.exception_handler(ValidationError)
    async def _pydantic_exc(_req: Request, exc: ValidationError) -> JSONResponse:
        problem = Problem(
            type="https://smadp.dev/problems/validation-error",
            title="Unprocessable Entity",
            status=422,
            detail=str(exc),
            instance=str(_req.url.path),
        )
        return JSONResponse(
            status_code=422,
            content=problem.model_dump(exclude_none=True),
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled.exception", path=_req.url.path)
        problem = Problem(
            type="https://smadp.dev/problems/internal-error",
            title="Internal Server Error",
            status=500,
            detail=type(exc).__name__,
            instance=str(_req.url.path),
        )
        return JSONResponse(
            status_code=500,
            content=problem.model_dump(exclude_none=True),
            media_type="application/problem+json",
        )

    # ------------------------------------------------------------- routers
    # Imported lazily so a missing optional dep doesn't block app creation.
    from smadp.api.routes import ROUTERS

    for router in ROUTERS:
        app.include_router(router, prefix="/api")

    return app


def _status_title(code: int) -> str:
    return {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        409: "Conflict",
        413: "Payload Too Large",
        422: "Unprocessable Entity",
        429: "Too Many Requests",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }.get(code, "Error")


# Module-level app so `uvicorn smadp.api.server:app` and TestClient(app) work.
app = create_app()


# Re-export for convenience.
__all__ = ["create_app", "JobStore", "TokenBucket", "RUBRIC_VERSION", "SCHEMA_VERSION"]
