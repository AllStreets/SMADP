"""`/api/sandbox/runs` — enqueue, list, fetch, and stream sandbox runs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from smadp.api.auth import require_operator_token
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
    dependencies=[Depends(require_operator_token)],
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
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    return _to_summary(record)


_TERMINAL_STATES = {"completed", "failed"}


def _row_state(sandbox_queue: Any, run_id: str, config: Any) -> tuple[str | None, str | None]:
    """Return (state, outcome) for a run, or (None, None) if it doesn't exist."""
    try:
        row = sandbox_queue.get_raw_row(run_id, config=config)
    except Exception:
        return None, None
    if row is None:
        return None, None
    return str(row.get("state") or ""), (row.get("outcome") or None)


@router.websocket("/runs/{run_id}/stream")
async def stream_run(websocket: WebSocket, run_id: str) -> None:
    """Stream a sandbox run's events as ``ConsoleEvent`` frames.

    Because the API server and the sandbox worker are separate processes (the
    in-process console bus cannot be shared), this endpoint achieves the same
    observable stream by *tailing the transcript JSONL* — which the runner's
    ``TranscriptWriter`` flushes per event. Each parsed transcript event is
    projected to a console frame; once the queue row is terminal we drain any
    remaining bytes, emit a terminal ``lifecycle`` frame carrying the final
    ``state``/``outcome``, and close.
    """
    await websocket.accept()
    sandbox_queue = _load_queue()
    if sandbox_queue is None:
        await websocket.send_text(
            json.dumps({"event": "error", "detail": "sandbox subsystem not installed"})
        )
        await websocket.close(code=1011)
        return

    # Local imports: the events/transcript/runner modules pull in the sandbox
    # subsystem which is optional at API-server import time.
    from smadp.sandbox.events import to_console_event
    from smadp.sandbox.runner import transcript_path_for
    from smadp.sandbox.transcripts import TranscriptEvent

    config = websocket.app.state.config

    state, _ = _row_state(sandbox_queue, run_id, config)
    if state is None:
        await websocket.send_text(json.dumps({"event": "not_found", "run_id": run_id}))
        await websocket.close(code=1000)
        return

    path = transcript_path_for(run_id, config=config)
    offset = 0

    async def _pump_new_events() -> None:
        nonlocal offset
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            for line in fh:
                if not line.endswith("\n"):
                    # Partial line flushed mid-write; stop and retry next tick.
                    break
                offset += len(line.encode("utf-8"))
                text = line.strip()
                if not text:
                    continue
                try:
                    event = TranscriptEvent.from_json_line(text)
                except Exception:  # noqa: S112
                    continue
                await websocket.send_text(json.dumps(to_console_event(run_id, event).to_payload()))

    try:
        while True:
            await _pump_new_events()
            state, outcome = _row_state(sandbox_queue, run_id, config)
            if state in _TERMINAL_STATES:
                # Final drain in case the last events flushed after our read.
                await _pump_new_events()
                await websocket.send_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "kind": "lifecycle",
                            "agent": "runner",
                            "ts": utcnow()
                            .isoformat(timespec="milliseconds")
                            .replace("+00:00", "Z"),
                            "payload": {"state": state, "outcome": outcome},
                        }
                    )
                )
                await websocket.close(code=1000)
                return
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return


@router.post(
    "/runs/{run_id}/halt",
    status_code=202,
    summary="Request an operator halt for a running sandbox run",
    dependencies=[Depends(require_operator_token)],
)
async def halt_run(request: Request, run_id: str) -> dict[str, Any]:
    """Operator-gated halt: set the queue's ``halt_requested`` flag.

    The runner polls the flag at 1 Hz and tears the run down (same teardown
    path as a tripwire halt). 404 if the run is unknown; 409 if it's already
    terminal; 202 with ``{run_id, halt_requested: true}`` on success.
    """
    _rate_limit(request)
    sandbox_queue = _load_queue()
    if sandbox_queue is None:
        raise HTTPException(status_code=503, detail="sandbox subsystem not installed")
    config = request.app.state.config
    try:
        accepted = sandbox_queue.request_halt(run_id, config=config)  # type: ignore[attr-defined]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not accepted:
        raise HTTPException(status_code=409, detail="run is already terminal")
    return {"run_id": run_id, "halt_requested": True}
