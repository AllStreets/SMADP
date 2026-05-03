"""`GET /api/chronicle` — paginated audit log."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request

from smadp.api.models import ChronicleResponse, ChronicleResponseItem, Page
from smadp.catalog.chronicle import Chronicle

router = APIRouter(tags=["chronicle"])


@router.get(
    "/chronicle",
    response_model=ChronicleResponse,
    summary="Paginated chronicle of catalog mutations",
)
async def get_chronicle(
    request: Request,
    since: Annotated[datetime | None, Query(description="ISO datetime lower bound (inclusive)")] = None,
    until: Annotated[datetime | None, Query(description="ISO datetime upper bound (inclusive)")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChronicleResponse:
    chronicle = Chronicle(request.app.state.config)
    events = list(chronicle.iter_events(since=since, until=until))
    events.sort(key=lambda e: e.ts, reverse=True)
    total = len(events)
    page_events = events[offset : offset + limit]

    items = [
        ChronicleResponseItem(
            ts=ev.ts,
            event=ev.event,
            by=ev.by,
            slug=ev.slug,
            pair=list(ev.pair) if ev.pair else None,
            verdict_id=ev.verdict_id,
            model=ev.model,
            outcome=ev.outcome,
            details=ev.details,
        )
        for ev in page_events
    ]
    return ChronicleResponse(
        items=items,
        page=Page(total=total, limit=limit, offset=offset),
    )
