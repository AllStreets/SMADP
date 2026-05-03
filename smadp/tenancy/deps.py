"""FastAPI dependencies for tenancy + RBAC.

Headers:

* ``X-SMADP-Workspace`` — workspace id the request operates against
* ``X-SMADP-User`` — caller's user id (resolved by upstream auth, e.g. an
  API gateway or session middleware; v2-D Plan 1 does not implement auth
  itself — that ships in Plan 7 alongside billing)

In v2-D Plan 1 these are simply read from headers without verification;
the auth surface attaches in a later plan. Until then, treat any callsite
that uses these dependencies as ``protected by upstream auth``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request

from smadp.config import Config
from smadp.schemas.tenancy import Role, Workspace
from smadp.tenancy import store


def _config_from_request(request: Request) -> Config:
    cfg = getattr(request.app.state, "config", None)
    if not isinstance(cfg, Config):
        raise HTTPException(
            status_code=500,
            detail="App state missing 'config' — wire it via app.state.config = Config().",
        )
    return cfg


def current_workspace(request: Request) -> Workspace:
    """Resolve the workspace from ``X-SMADP-Workspace`` or 403/404."""
    ws_id = request.headers.get("X-SMADP-Workspace")
    if not ws_id:
        raise HTTPException(status_code=403, detail="X-SMADP-Workspace header required")
    cfg = _config_from_request(request)
    try:
        return store.get_workspace(ws_id, config=cfg)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def current_user_id(request: Request) -> str:
    user_id = request.headers.get("X-SMADP-User")
    if not user_id:
        raise HTTPException(status_code=403, detail="X-SMADP-User header required")
    return user_id


def require_role(min_role: Role) -> Callable[..., Any]:
    """Return a dependency that asserts the caller has ``>= min_role`` in workspace."""

    def _check(
        request: Request,
        ws: Workspace = Depends(current_workspace),
        user_id: str = Depends(current_user_id),
    ) -> Workspace:
        cfg = _config_from_request(request)
        actual = store.get_member_role(workspace_id=ws.id, user_id=user_id, config=cfg)
        if actual is None:
            raise HTTPException(
                status_code=403,
                detail=f"User {user_id!r} is not a member of {ws.id!r}",
            )
        if actual < min_role:
            raise HTTPException(
                status_code=403,
                detail=f"Need {min_role.value} or higher; have {actual.value}",
            )
        return ws

    return _check


__all__ = ["current_user_id", "current_workspace", "require_role"]
