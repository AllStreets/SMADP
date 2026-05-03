"""`GET /api/search` — full-text search across profiles + verdicts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from smadp.api.models import SearchResponse, SearchResponseItem
from smadp.catalog.index import CatalogIndex

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Full-text search profiles + verdicts",
)
async def search(
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=200, description="search query")],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SearchResponse:
    index = CatalogIndex(request.app.state.config)
    hits = index.search(q, limit=limit)
    return SearchResponse(
        query=q,
        items=[
            SearchResponseItem(
                kind=h.kind,
                ref=h.ref,
                title=h.title,
                snippet=h.snippet,
                score=h.score,
            )
            for h in hits
        ],
    )
