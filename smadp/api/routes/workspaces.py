"""FastAPI router for /api/workspaces (and /api/workspaces/{id}/members)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict

from smadp.schemas.tenancy import Member, Plan, Role, Workspace
from smadp.tenancy import store

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class CreateWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    plan: Plan


class AddMemberBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: Role


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Workspace)
def create_workspace(body: CreateWorkspaceBody) -> Workspace:
    return store.create_workspace(name=body.name, plan=body.plan)


@router.get("", response_model=list[Workspace])
def list_workspaces() -> list[Workspace]:
    return store.list_workspaces()


@router.get("/{workspace_id}", response_model=Workspace)
def get_workspace(workspace_id: str) -> Workspace:
    try:
        return store.get_workspace(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: str) -> Response:
    try:
        store.delete_workspace(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{workspace_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=Member,
)
def add_member(workspace_id: str, body: AddMemberBody) -> Member:
    # Validate workspace exists first.
    try:
        store.get_workspace(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return store.add_member(
        workspace_id=workspace_id, user_id=body.user_id, role=body.role
    )


@router.get("/{workspace_id}/members", response_model=list[Member])
def list_members(workspace_id: str) -> list[Member]:
    try:
        store.get_workspace(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return store.list_members(workspace_id=workspace_id)


__all__ = ["router"]
