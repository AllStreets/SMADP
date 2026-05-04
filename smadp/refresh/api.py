"""FastAPI router for /api/refresh — manual enqueue endpoint (admin role)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from smadp.config import Config, load_config
from smadp.refresh import queue
from smadp.schemas.refresh import RefreshQueueItem, RefreshTrigger
from smadp.schemas.tenancy import Role, Workspace
from smadp.tenancy.deps import current_user_id, current_workspace, require_role

router = APIRouter(prefix="/refresh", tags=["refresh"])


class _ManualRefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict_id: str = Field(min_length=3, max_length=256)
    reason: str | None = Field(default=None, max_length=512)


@router.post(
    "",
    response_model=RefreshQueueItem,
    status_code=status.HTTP_201_CREATED,
)
def enqueue_manual_refresh(
    body: _ManualRefreshBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: Workspace = Depends(require_role(Role.ADMIN)),
) -> Any:
    cfg: Config = load_config()
    detail: dict[str, Any] = {"workspace_id": workspace.id, "user_id": user_id}
    if body.reason:
        detail["reason"] = body.reason
    return queue.enqueue(
        verdict_id=body.verdict_id,
        trigger=RefreshTrigger.MANUAL,
        trigger_detail=detail,
        config=cfg,
    )


__all__ = ["router"]
