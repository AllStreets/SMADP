"""Claim verification: repo (httpx), DNS (dnspython), email (token compare)."""

from __future__ import annotations

import hmac
import time
from typing import Final

import httpx
import structlog

from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimVerification,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
    VendorClaim,
)

log = structlog.get_logger(__name__)

_HTTP_TIMEOUT_S: Final[float] = 10.0
_RETRY_BACKOFFS: tuple[float, ...] = (1.0, 4.0)
_OWNER_FILE_SUFFIX: Final[str] = "/.smadp/owner.txt"


def verify_repo(*, claim: VendorClaim, evidence: RepoEvidence) -> ClaimVerification:
    url = evidence.repo_url.rstrip("/") + _OWNER_FILE_SUFFIX
    last_exc: Exception | None = None
    last_status: int | None = None
    last_body: str | None = None

    attempts = (0.0,) + _RETRY_BACKOFFS  # 1 initial + N retries
    for i, backoff in enumerate(attempts):
        if backoff > 0.0:
            time.sleep(backoff)
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
                resp = client.get(url)
            last_status = resp.status_code
            last_body = resp.text
            if 500 <= resp.status_code < 600:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue
            if resp.status_code != 200:
                return ClaimVerification(
                    verified=False, detail=f"repo HTTP {resp.status_code}"
                )
            body = resp.text.strip()
            if hmac.compare_digest(body, claim.token):
                return ClaimVerification(
                    verified=True, detail=f"repo HTTP 200; token match (attempt {i + 1})"
                )
            return ClaimVerification(verified=False, detail="repo token mismatch")
        except (httpx.TransportError, RuntimeError) as exc:
            last_exc = exc
            continue
    detail = f"transport error: {last_exc!r}"
    if last_status is not None:
        detail += f" (last HTTP={last_status})"
    return ClaimVerification(verified=False, detail=detail)


__all__ = [
    "verify_repo",
]
