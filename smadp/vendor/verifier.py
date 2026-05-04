"""Claim verification: repo (httpx), DNS (dnspython), email (token compare)."""

from __future__ import annotations

import hmac
import time
from typing import Final

import dns.exception
import dns.resolver
import httpx
import structlog

from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimVerification,
    DnsEvidence,
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

    attempts = (0.0, *_RETRY_BACKOFFS)  # 1 initial + N retries
    for i, backoff in enumerate(attempts):
        if backoff > 0.0:
            time.sleep(backoff)
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
                resp = client.get(url)
            last_status = resp.status_code
            if 500 <= resp.status_code < 600:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue
            if resp.status_code != 200:
                return ClaimVerification(verified=False, detail=f"repo HTTP {resp.status_code}")
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


_DNS_LIFETIME_S: Final[float] = 10.0
_DNS_PREFIX: Final[str] = "_smadp-owner."


def _resolve_txt(name: str):
    """Indirection for monkeypatching in tests."""
    resolver = dns.resolver.Resolver(configure=True)
    resolver.lifetime = _DNS_LIFETIME_S
    resolver.timeout = _DNS_LIFETIME_S
    return resolver.resolve(name, "TXT")


def verify_dns(*, claim: VendorClaim, evidence: DnsEvidence) -> ClaimVerification:
    name = _DNS_PREFIX + evidence.domain
    try:
        answers = _resolve_txt(name)
    except dns.resolver.NXDOMAIN:
        return ClaimVerification(verified=False, detail=f"NXDOMAIN for {name}")
    except dns.resolver.NoAnswer:
        return ClaimVerification(verified=False, detail=f"NoAnswer for {name}")
    except dns.exception.Timeout:
        return ClaimVerification(verified=False, detail=f"Timeout resolving {name}")
    except dns.exception.DNSException as exc:
        return ClaimVerification(
            verified=False, detail=f"DNS error for {name}: {exc.__class__.__name__}"
        )
    for rdata in answers:
        for chunk in rdata.strings:
            value = chunk.decode("utf-8", errors="replace").strip()
            if hmac.compare_digest(value, claim.token):
                return ClaimVerification(
                    verified=True, detail=f"DNS TXT match at {evidence.domain}"
                )
    return ClaimVerification(
        verified=False,
        detail=f"DNS TXT mismatch at {evidence.domain} (no chunk matched token)",
    )


def verify_email(*, claim: VendorClaim, evidence: TokenEvidence) -> ClaimVerification:
    if hmac.compare_digest(evidence.token, claim.token):
        return ClaimVerification(verified=True, detail="email token match")
    return ClaimVerification(verified=False, detail="email token mismatch")


def build_email_magic_link(*, public_base_url: str, claim_id: str, token: str) -> str:
    base = public_base_url.rstrip("/")
    return f"{base}/vendor/claims/{claim_id}/verify?token={token}"


def verify(
    *,
    claim: VendorClaim,
    evidence: RepoEvidence | DnsEvidence | TokenEvidence,
) -> ClaimVerification:
    if claim.method == ClaimMethod.REPO:
        if not isinstance(evidence, RepoEvidence):
            raise ValueError("evidence type must be RepoEvidence for method=repo")
        return verify_repo(claim=claim, evidence=evidence)
    if claim.method == ClaimMethod.DNS:
        if not isinstance(evidence, DnsEvidence):
            raise ValueError("evidence type must be DnsEvidence for method=dns")
        return verify_dns(claim=claim, evidence=evidence)
    if claim.method == ClaimMethod.EMAIL:
        if not isinstance(evidence, TokenEvidence):
            raise ValueError("evidence type must be TokenEvidence for method=email")
        return verify_email(claim=claim, evidence=evidence)
    raise ValueError(f"unknown claim method: {claim.method!r}")


__all__ = [
    "build_email_magic_link",
    "verify",
    "verify_dns",
    "verify_email",
    "verify_repo",
]
