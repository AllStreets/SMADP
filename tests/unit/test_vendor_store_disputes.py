"""Unit tests for vendor.store dispute CRUD + transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.dispute import DisputeDecision, DisputeStatus, RequestedOutcome
from smadp.schemas.tenancy import Plan
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


def _file(cfg, ws):
    return store.file_dispute(
        workspace_id=ws,
        verdict_id="vdt_X",
        vendor_user_id="user_a",
        argument_md="we believe this is wrong because ...",
        requested_outcome=RequestedOutcome.REEVAL,
        config=cfg,
    )


def test_file_dispute_starts_in_triage(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    assert d.id.startswith("dsp_")
    assert d.status == DisputeStatus.TRIAGE
    assert d.triaged_at is None
    assert d.sla_breached_at is None


def test_triage_to_spam(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.SPAM,
        rationale_md=None,
        config=cfg,
    )
    loaded = store.get_dispute(dispute_id=d.id, config=cfg)
    assert loaded.status == DisputeStatus.SPAM
    assert loaded.resolved_at is not None


def test_triage_to_pending_review_sets_sla(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.SUBSTANTIVE,
        rationale_md=None,
        config=cfg,
    )
    loaded = store.get_dispute(dispute_id=d.id, config=cfg)
    assert loaded.status == DisputeStatus.PENDING_REVIEW
    assert loaded.triaged_at is not None
    assert loaded.sla_breached_at is not None
    # 5 business days >= 5 calendar days
    assert (loaded.sla_breached_at - loaded.triaged_at).days >= 5


def test_pending_review_to_resolved_reeval_requires_rationale(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id, decision=DisputeDecision.SUBSTANTIVE, rationale_md=None, config=cfg
    )
    with pytest.raises(ValueError, match="rationale"):
        store.update_dispute_status(
            dispute_id=d.id,
            decision=DisputeDecision.REEVAL,
            rationale_md=None,
            config=cfg,
        )


def test_pending_review_to_resolved_reeval(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id, decision=DisputeDecision.SUBSTANTIVE, rationale_md=None, config=cfg
    )
    store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.REEVAL,
        rationale_md="re-running with new criteria",
        config=cfg,
    )
    loaded = store.get_dispute(dispute_id=d.id, config=cfg)
    assert loaded.status == DisputeStatus.RESOLVED_REEVAL
    assert loaded.decision_rationale_md == "re-running with new criteria"


def test_pending_review_to_resolved_stands(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    store.update_dispute_status(
        dispute_id=d.id, decision=DisputeDecision.SUBSTANTIVE, rationale_md=None, config=cfg
    )
    store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.STANDS,
        rationale_md="evidence reviewed; verdict confirmed",
        config=cfg,
    )
    loaded = store.get_dispute(dispute_id=d.id, config=cfg)
    assert loaded.status == DisputeStatus.RESOLVED_STANDS


def test_invalid_transition_triage_to_reeval_raises(cfg: Config, workspace_id: str):
    d = _file(cfg, workspace_id)
    with pytest.raises(ValueError, match="invalid dispute transition"):
        store.update_dispute_status(
            dispute_id=d.id,
            decision=DisputeDecision.REEVAL,
            rationale_md="x",
            config=cfg,
        )


def test_list_disputes_for_verdict(cfg: Config, workspace_id: str):
    a = _file(cfg, workspace_id)
    b = store.file_dispute(
        workspace_id=workspace_id,
        verdict_id="vdt_X",
        vendor_user_id="user_b",
        argument_md="another argument",
        requested_outcome=RequestedOutcome.AMEND,
        config=cfg,
    )
    ids = {d.id for d in store.list_disputes(workspace_id=workspace_id, verdict_id="vdt_X", config=cfg)}
    assert ids == {a.id, b.id}
