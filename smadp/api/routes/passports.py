"""FastAPI router for passport HTML rendering."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Workspace
from smadp.tenancy.deps import current_workspace

router = APIRouter(prefix="/passports", tags=["passports"])


def _slug_decode(slug: str) -> str:
    """Routes use ``__`` as a path-safe separator for slashed slugs."""
    return slug.replace("__", "/", 1)


@router.get(
    "/{slug_a}/{slug_b}.html",
    response_class=Response,
    responses={
        200: {"content": {"text/html": {}}},
        404: {"description": "Verdict not found"},
        403: {"description": "Workspace header missing or unauthorized"},
    },
)
def get_passport(
    slug_a: str,
    slug_b: str,
    workspace: Workspace = Depends(current_workspace),
) -> Response:
    repo = CatalogRepo()
    try:
        verdict_obj = repo.load_verdict(_slug_decode(slug_a), _slug_decode(slug_b))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    verdict_dict = verdict_obj.model_dump(mode="json")

    try:
        frameworks_dict = repo.load_frameworks_meta()
    except (FileNotFoundError, AttributeError):
        frameworks_dict = {}

    html = render_passport(
        verdict=verdict_dict,
        frameworks=frameworks_dict,
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=workspace.id,
        rendered_at=None,
    )
    return Response(content=html, media_type="text/html; charset=utf-8")


__all__ = ["router"]
