"""FastAPI router for /api/webhooks/subscriptions."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from smadp.schemas.tenancy import Workspace
from smadp.schemas.webhooks import EventType, IntegrationKind, Subscription
from smadp.tenancy.deps import current_workspace
from smadp.webhooks import store

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class _CreateSubscriptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    event_types: list[EventType]
    integration_kind: IntegrationKind = IntegrationKind.GENERIC
    integration_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme == "https":
            return v
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return v
        raise ValueError("Subscription URL must be https:// (or http://localhost for dev)")

    @field_validator("event_types")
    @classmethod
    def _nonempty(cls, v: list[EventType]) -> list[EventType]:
        if not v:
            raise ValueError("event_types must not be empty")
        return v


class _CreateSubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription: Subscription
    secret: str


@router.post(
    "/subscriptions",
    response_model=_CreateSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    body: _CreateSubscriptionBody,
    workspace: Workspace = Depends(current_workspace),
) -> Any:
    sub, secret = store.create_subscription(
        workspace_id=workspace.id,
        url=body.url,
        event_types=body.event_types,
        integration_kind=body.integration_kind,
        integration_config=body.integration_config,
    )
    return _CreateSubscriptionResponse(subscription=sub, secret=secret)


@router.get("/subscriptions", response_model=list[Subscription])
def list_subscriptions(
    workspace: Workspace = Depends(current_workspace),
) -> Any:
    return store.list_subscriptions(workspace_id=workspace.id)


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(
    subscription_id: str,
    workspace: Workspace = Depends(current_workspace),
) -> Response:
    try:
        existing = store.get_subscription(subscription_id=subscription_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if existing.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="subscription not found in this workspace")
    store.deactivate_subscription(subscription_id=subscription_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
