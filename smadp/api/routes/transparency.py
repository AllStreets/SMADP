"""FastAPI router for /api/transparency — read-only journal access."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from smadp.schemas.transparency import SignedEvent
from smadp.transparency.journal import iter_events

router = APIRouter(prefix="/transparency", tags=["transparency"])


@router.get("/events", response_model=list[SignedEvent])
def list_events(
    event_type: Annotated[
        str | None,
        Query(description="Filter to events of this type (exact match)"),
    ] = None,
) -> list[SignedEvent]:
    out: list[SignedEvent] = []
    for ev in iter_events():
        if event_type is not None and ev.event_type != event_type:
            continue
        out.append(ev)
    return out


@router.get("/events/{event_id}", response_model=SignedEvent)
def get_event(event_id: int) -> SignedEvent:
    for ev in iter_events():
        if ev.id == event_id:
            return ev
    raise HTTPException(status_code=404, detail=f"No event with id {event_id}")


__all__ = ["router"]
