"""Unit tests for vendor.verifier repo method."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.vendor import ClaimMethod, RepoEvidence
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
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )


@respx.mock
def test_verify_repo_happy_path(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=claim.token + "\n")
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is True
    assert "200" in result.detail


@respx.mock
def test_verify_repo_token_mismatch(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text="not-the-token")
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is False
    assert "mismatch" in result.detail.lower()


@respx.mock
def test_verify_repo_404_no_retry(cfg: Config, workspace_id: str):
    claim = _claim(cfg, workspace_id)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(404)
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is False
    assert "404" in result.detail


@respx.mock
def test_verify_repo_5xx_then_success_retries(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    # Disable backoff sleeps so the test is fast.
    monkeypatch.setattr(verifier, "_RETRY_BACKOFFS", (0.0, 0.0))
    claim = _claim(cfg, workspace_id)
    route = respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, text=claim.token)]
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is True
    assert route.call_count == 2


@respx.mock
def test_verify_repo_transport_exhaust(
    cfg: Config, workspace_id: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(verifier, "_RETRY_BACKOFFS", (0.0, 0.0))
    claim = _claim(cfg, workspace_id)
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        side_effect=httpx.ConnectError("dead")
    )
    result = verifier.verify_repo(claim=claim, evidence=RepoEvidence(repo_url=claim.evidence_url))
    assert result.verified is False
    assert "dead" in result.detail.lower() or "connect" in result.detail.lower()
