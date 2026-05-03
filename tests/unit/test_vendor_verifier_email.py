"""Unit tests for vendor.verifier email + dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.vendor import (
    ClaimMethod,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
)
from smadp.tenancy import store as tenancy
from smadp.vendor import store, verifier


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def _claim_email(cfg, ws):
    return store.create_claim(
        workspace_id=ws,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.EMAIL,
        evidence_url=None,
        config=cfg,
    )


def test_verify_email_token_match(cfg: Config, workspace_id: str):
    claim = _claim_email(cfg, workspace_id)
    result = verifier.verify_email(claim=claim, evidence=TokenEvidence(token=claim.token))
    assert result.verified is True
    assert "match" in result.detail.lower()


def test_verify_email_token_mismatch(cfg: Config, workspace_id: str):
    claim = _claim_email(cfg, workspace_id)
    result = verifier.verify_email(claim=claim, evidence=TokenEvidence(token="x" * 32))
    assert result.verified is False


def test_dispatch_routes_repo(cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch):
    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    called: dict[str, object] = {}

    def fake_repo(*, claim, evidence):
        called["claim"] = claim
        called["evidence"] = evidence
        return verifier.ClaimVerification(verified=True, detail="stub")

    monkeypatch.setattr(verifier, "verify_repo", fake_repo)
    result = verifier.verify(claim=claim, evidence=RepoEvidence(repo_url="https://github.com/o/r/raw/main"))
    assert result.verified is True
    assert called["claim"] is claim


def test_dispatch_routes_dns(cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch):
    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )
    monkeypatch.setattr(
        verifier,
        "verify_dns",
        lambda *, claim, evidence: verifier.ClaimVerification(verified=True, detail="dns-stub"),
    )
    result = verifier.verify(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is True
    assert "dns-stub" in result.detail


def test_dispatch_method_evidence_mismatch_raises(cfg: Config, workspace_id: str):
    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    with pytest.raises(ValueError, match="evidence type"):
        verifier.verify(claim=claim, evidence=DnsEvidence(domain="acme.com"))


def test_email_magic_link_url():
    url = verifier.build_email_magic_link(
        public_base_url="https://smadp.example",
        claim_id="vc_AB12CD34",
        token="t" * 32,
    )
    assert url == "https://smadp.example/vendor/claims/vc_AB12CD34/verify?token=" + ("t" * 32)
