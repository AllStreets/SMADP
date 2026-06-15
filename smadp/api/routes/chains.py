"""`/api/chains` — list, fetch, create, delete multi-agent chains.

Backed by `CatalogRepo` (writes JSON files to `catalog/chains/`) and the
chronicle audit log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from smadp.api.auth import require_operator_token
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.schemas.chain import Chain
from smadp.utils.time import utcnow

router = APIRouter(prefix="/chains", tags=["chains"])


def _rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.rate_limiter
    if not limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def _to_dump(chain: Chain) -> dict[str, Any]:
    return chain.model_dump(mode="json", by_alias=True, exclude_none=True)


@router.get("", summary="List all chains in the catalog")
async def list_chains(request: Request) -> dict[str, Any]:
    repo = CatalogRepo(request.app.state.config)
    items = [_to_dump(c) for c in repo.list_chains()]
    return {"items": items, "total": len(items)}


@router.get(
    "/{chain_id}/composition",
    summary="Compute the deterministic composition for an authored chain (read-only)",
)
async def get_chain_composition(request: Request, chain_id: str) -> dict[str, Any]:
    """Compose an authored chain on the fly from its pairwise verdicts.

    Read-only and unauthenticated: no token, no write, no operator gate. Every
    number here is computed deterministically in Python (never the LLM).
    """
    from smadp.autopilot.chain_composer import compose_chain_candidate

    repo = CatalogRepo(request.app.state.config)
    try:
        chain = repo.load_chain(chain_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    candidate, composed = compose_chain_candidate(repo, chain)
    return {
        "chain_id": chain_id,
        "composite_score": composed.composite,
        "confidence": composed.confidence,
        "max_severity": composed.max_severity,
        "severities": composed.severities,
        "missing_links": composed.missing_links,
        "composed_from": candidate.composed_from,
    }


@router.get("/{chain_id}", summary="Fetch a single chain by id")
async def get_chain(request: Request, chain_id: str) -> dict[str, Any]:
    repo = CatalogRepo(request.app.state.config)
    try:
        return _to_dump(repo.load_chain(chain_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chain",
    dependencies=[Depends(require_operator_token)],
)
async def create_chain(request: Request, body: Chain) -> dict[str, Any]:
    _rate_limit(request)
    cfg = request.app.state.config
    repo = CatalogRepo(cfg)
    chronicle = Chronicle(cfg)

    if repo.chain_path(body.chain_id).exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"chain already exists: {body.chain_id}",
        )
    # Stamp server-side timestamps so clients don't have to.
    now = utcnow()
    chain = body.model_copy(update={"first_seen_at": now, "last_refreshed_at": now})

    path = repo.save_chain(chain)
    chronicle.record(
        "chain.created",
        by="api",
        details={
            "chain_id": chain.chain_id,
            "path": str(path),
            "participants": [p.slug for p in chain.participants],
            "topology": chain.topology,
        },
    )
    return _to_dump(chain)


@router.delete(
    "/{chain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_operator_token)],
)
async def delete_chain(request: Request, chain_id: str) -> Response:
    _rate_limit(request)
    cfg = request.app.state.config
    repo = CatalogRepo(cfg)
    chronicle = Chronicle(cfg)

    path = repo.chain_path(chain_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"chain not found: {chain_id}")
    path.unlink()
    chronicle.record("chain.deleted", by="api", details={"chain_id": chain_id, "path": str(path)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
