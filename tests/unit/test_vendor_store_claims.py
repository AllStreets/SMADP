"""Unit tests for vendor.store claim CRUD."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.vendor import ClaimMethod, ClaimStatus
from smadp.tenancy import store as tenancy
from smadp.vendor import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_create_claim_returns_token(cfg: Config, workspace_id: str):
    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    assert claim.id.startswith("vc_")
    assert claim.status == ClaimStatus.PENDING
    assert len(claim.token) >= 32
    assert claim.evidence_url == "https://github.com/o/r/raw/main"


def test_get_claim_roundtrip(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )
    b = store.get_claim(claim_id=a.id, config=cfg)
    assert a == b


def test_list_claims_for_workspace(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    b = store.create_claim(
        workspace_id=workspace_id,
        agent_id="cursor",
        vendor_user_id="u",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )
    ids = {c.id for c in store.list_claims(workspace_id=workspace_id, config=cfg)}
    assert ids == {a.id, b.id}


def test_list_claims_filter_by_agent(cfg: Config, workspace_id: str):
    store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    b = store.create_claim(
        workspace_id=workspace_id,
        agent_id="cursor",
        vendor_user_id="u",
        method=ClaimMethod.DNS,
        evidence_url=None,
        config=cfg,
    )
    matched = store.list_claims(workspace_id=workspace_id, agent_id="cursor", config=cfg)
    assert {c.id for c in matched} == {b.id}


def test_mark_claim_verified(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    store.mark_claim_verified(claim_id=a.id, config=cfg)
    loaded = store.get_claim(claim_id=a.id, config=cfg)
    assert loaded.status == ClaimStatus.VERIFIED
    assert loaded.granted_at is not None


def test_revoke_claim(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    store.revoke_claim(claim_id=a.id, config=cfg)
    loaded = store.get_claim(claim_id=a.id, config=cfg)
    assert loaded.status == ClaimStatus.REVOKED
    assert loaded.revoked_at is not None


def test_get_claim_unknown_raises(cfg: Config):
    with pytest.raises(KeyError):
        store.get_claim(claim_id="vc_NOPE0000", config=cfg)


def test_find_verified_claim_lookup(cfg: Config, workspace_id: str):
    a = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="user_a",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    assert (
        store.find_verified_claim(
            workspace_id=workspace_id,
            vendor_user_id="user_a",
            agent_id="claude-code",
            config=cfg,
        )
        is None
    )
    store.mark_claim_verified(claim_id=a.id, config=cfg)
    found = store.find_verified_claim(
        workspace_id=workspace_id,
        vendor_user_id="user_a",
        agent_id="claude-code",
        config=cfg,
    )
    assert found is not None and found.id == a.id
