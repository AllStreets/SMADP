"""Operator-token authentication for write endpoints.

SMADP's API binds to loopback and was historically unauthenticated. Read
endpoints (the public catalog) stay open; every endpoint that *writes* to the
catalog now requires an operator bearer token so that exposing the API — or a
leaked client — cannot mutate the catalog.

Design:

- The token is read from ``SMADP_API_TOKEN``.
- If the variable is unset, write endpoints return **503** (fail-safe): the
  server refuses to accept writes it cannot authenticate, rather than falling
  open. This is deliberate — an operator must configure a token before the
  write surface is usable.
- A request must present ``Authorization: Bearer <token>`` (constant-time
  compared) or it gets **401**.

Generate a token:

    python -c "import secrets; print(secrets.token_urlsafe(32))"

Store it at ``~/.smadp/api-token`` (mode 600) and inject it via the launchd
plist's EnvironmentVariables. See docs/SECURITY-NOTES.md.
"""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request, status

_ENV_VAR = "SMADP_API_TOKEN"


def _configured_token() -> str:
    return os.environ.get(_ENV_VAR, "").strip()


async def require_operator_token(request: Request) -> None:
    """FastAPI dependency guarding write endpoints.

    503 when no token is configured (fail-safe); 401 when the presented
    bearer token is missing or wrong.
    """
    expected = _configured_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Write endpoints are disabled: no SMADP_API_TOKEN is configured on the server."
            ),
        )

    header = request.headers.get("Authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing operator bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid operator bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
