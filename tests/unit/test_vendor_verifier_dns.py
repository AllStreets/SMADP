"""Unit tests for vendor.verifier DNS method."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.vendor import ClaimMethod, DnsEvidence
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


def _claim(cfg, ws):
    return store.create_claim(
        workspace_id=ws,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )


def _txt_answer(values: list[str]):
    """Build a fake dnspython answer iterable."""
    answers = []
    for v in values:
        m = MagicMock()
        m.strings = [v.encode("utf-8")]
        answers.append(m)
    return answers


def test_verify_dns_happy_path(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    with patch.object(verifier, "_resolve_txt", return_value=_txt_answer(["junk", claim.token])):
        result = verifier.verify_dns(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is True
    assert "acme.com" in result.detail


def test_verify_dns_token_mismatch(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    with patch.object(verifier, "_resolve_txt", return_value=_txt_answer(["other-token"])):
        result = verifier.verify_dns(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is False
    assert "mismatch" in result.detail.lower()


def test_verify_dns_nxdomain(cfg: Config, workspace_id: str):
    import dns.resolver

    claim = _claim(cfg, workspace_id)
    with patch.object(verifier, "_resolve_txt", side_effect=dns.resolver.NXDOMAIN()):
        result = verifier.verify_dns(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is False
    assert "nxdomain" in result.detail.lower()


def test_verify_dns_timeout(cfg: Config, workspace_id: str):
    import dns.exception

    claim = _claim(cfg, workspace_id)
    with patch.object(verifier, "_resolve_txt", side_effect=dns.exception.Timeout()):
        result = verifier.verify_dns(claim=claim, evidence=DnsEvidence(domain="acme.com"))
    assert result.verified is False
    assert "timeout" in result.detail.lower()
