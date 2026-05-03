"""Unit tests for smadp.schemas.vendor."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimStatus,
    ClaimVerification,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
    VendorClaim,
    VendorResponse,
)


def test_claim_method_values_locked():
    assert {m.value for m in ClaimMethod} == {"repo", "dns", "email"}


def test_claim_status_values_locked():
    assert {s.value for s in ClaimStatus} == {"pending", "verified", "revoked"}


def test_vendor_claim_id_pattern_enforced():
    with pytest.raises(ValidationError):
        VendorClaim(
            id="bad-id",
            workspace_id="ws_ABCD1234",
            agent_id="claude-code",
            vendor_user_id="user_a",
            method=ClaimMethod.REPO,
            token="t" * 32,
            status=ClaimStatus.PENDING,
            evidence_url=None,
            created_at=datetime.now(UTC),
            granted_at=None,
            revoked_at=None,
        )


def test_vendor_claim_agent_id_pattern_enforced():
    with pytest.raises(ValidationError):
        VendorClaim(
            id="vc_AB12CD34",
            workspace_id="ws_ABCD1234",
            agent_id="Bad_Slug!",
            vendor_user_id="user_a",
            method=ClaimMethod.REPO,
            token="t" * 32,
            status=ClaimStatus.PENDING,
            evidence_url=None,
            created_at=datetime.now(UTC),
            granted_at=None,
            revoked_at=None,
        )


def test_vendor_response_id_pattern_enforced():
    with pytest.raises(ValidationError):
        VendorResponse(
            id="vr_bad",
            workspace_id="ws_ABCD1234",
            verdict_id="vdt_X",
            vendor_user_id="user_a",
            body_md="hi",
            created_at=datetime.now(UTC),
        )


def test_repo_evidence_requires_https_or_localhost():
    RepoEvidence(repo_url="https://github.com/o/r/raw/main")
    RepoEvidence(repo_url="http://localhost:9000/r/raw/main")
    with pytest.raises(ValidationError):
        RepoEvidence(repo_url="ftp://example.com/owner.txt")


def test_dns_evidence_strips_scheme_and_path():
    e = DnsEvidence(domain="ACME.com")
    assert e.domain == "acme.com"
    with pytest.raises(ValidationError):
        DnsEvidence(domain="not a domain")


def test_email_evidence_basic():
    e = EmailEvidence(email_address="vendor@acme.com")
    assert e.email_address == "vendor@acme.com"
    with pytest.raises(ValidationError):
        EmailEvidence(email_address="not-an-email")


def test_token_evidence_min_length():
    with pytest.raises(ValidationError):
        TokenEvidence(token="short")
    TokenEvidence(token="t" * 32)


def test_claim_verification_record():
    v = ClaimVerification(verified=True, detail="ok")
    assert v.verified is True
    assert v.detail == "ok"
