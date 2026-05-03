"""`/api/sandbox/runs` — enqueue, list, fetch, and stream sandbox runs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from smadp.api.models import (
    SandboxRunListResponse,
    SandboxRunRequest,
    SandboxRunSummary,
)
from smadp.catalog.repo import CatalogRepo
from smadp.utils.slug import sort_pair
from smadp.utils.time import utcnow

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


def _rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.rate_limiter
    if not limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def _to_summary(record: dict[str, Any]) -> SandboxRunSummary:
    pair = record.get("pair") or [record.get("slug_a"), record.get("slug_b")]
    return SandboxRunSummary(
        run_id=str(record.get("run_id") or record.get("id") or ""),
        pair=[str(p) for p in pair if p],
        scenario=record.get("scenario"),
        status=str(record.get("status", "queued")),
        outcome=record.get("outcome"),
        queued_at=_coerce_dt(record.get("queued_at") or record.get("created_at") or utcnow()),
        started_at=_maybe_dt(record.get("started_at")),
        completed_at=_maybe_dt(record.get("completed_at")),
    )


def _coerce_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return utcnow()


def _maybe_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    return _coerce_dt(value)


def _load_queue() -> Any:
    try:
        from smadp.sandbox import queue as sandbox_queue  # type: ignore[import-not-found]

        return sandbox_queue
    except Exception:
        return None


@router.post(
    "/runs",
    response_model=SandboxRunSummary,
    summary="Enqueue a sandbox run for a pair of agents",
    status_code=202,
)
async def enqueue_run(request: Request, payload: SandboxRunRequest) -> SandboxRunSummary:
    _rate_limit(request)
    cfg = request.app.state.config
    repo = CatalogRepo(cfg)

    a, b = sort_pair(payload.agents[0], payload.agents[1])
    for slug in (a, b):
        if not repo.profile_exists(slug):
            raise HTTPException(status_code=404, detail=f"unknown agent: {slug}")

    sandbox_queue = _load_queue()
    if sandbox_queue is None:
        raise HTTPException(status_code=503, detail="sandbox subsystem not installed")
    try:
        record = sandbox_queue.enqueue_sandbox_run(  # type: ignore[attr-defined]
            slug_a=a, slug_b=b, scenario=payload.scenario
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not isinstance(record, dict):
        record = {"run_id": str(record), "pair": [a, b], "scenario": payload.scenario}
    return _to_summary(record)


@router.get(
    "/runs",
    response_model=SandboxRunListResponse,
    summary="List recent sandbox runs",
)
async def list_runs(request: Request, limit: int = 50) -> SandboxRunListResponse:
    sandbox_queue = _load_queue()
    if sandbox_queue is None:
        return SandboxRunListResponse(items=[])
    try:
        records = list(sandbox_queue.iter_runs(limit=limit))  # type: ignore[attr-defined]
    except TypeError:
        records = list(sandbox_queue.iter_runs())  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SandboxRunListResponse(items=[_to_summary(r) for r in records[:limit]])


@router.get(
    "/runs/{run_id}",
    response_model=SandboxRunSummary,
    summary="Fetch a sandbox run by id",
)
async def get_run(request: Request, run_id: str) -> SandboxRunSummary:
    sandbox_queue = _load_queue()
    if sandbox_queue is None:
        raise HTTPException(status_code=503, detail="sandbox subsystem not installed")
    try:
        record = sandbox_queue.get_run_status(run_id)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    return _to_summary(record)


@router.websocket("/runs/{run_id}/stream")
async def stream_run(websocket: WebSocket, run_id: str) -> None:
    """Stream progress lines for a sandbox run.

    The protocol is line-delimited JSON; each frame is one event from the
    sandbox queue. We poll the queue every 500ms and forward changes.
    """
    await websocket.accept()
    sandbox_queue = _load_queue()
    if sandbox_queue is None:
        await websocket.send_text(
            json.dumps({"event": "error", "detail": "sandbox subsystem not installed"})
        )
        await websocket.close(code=1011)
        return

    last_payload: str | None = None
    try:
        while True:
            try:
                record = sandbox_queue.get_run_status(run_id)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                await websocket.send_text(
                    json.dumps({"event": "error", "detail": str(exc)})
                )
                await websocket.close(code=1011)
                return
            if record is None:
                await websocket.send_text(
                    json.dumps({"event": "not_found", "run_id": run_id})
                )
                await websocket.close(code=1000)
                return
            payload = json.dumps(record, default=str, sort_keys=True)
            if payload != last_payload:
                await websocket.send_text(payload)
                last_payload = payload
            status = str(record.get("status", "")) if isinstance(record, dict) else ""
            if status in {"succeeded", "failed", "errored", "completed"}:
                await websocket.close(code=1000)
                return
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
