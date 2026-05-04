"""Tests for the dispute-resolution retrofit added by v2-D Plan 5.

``update_dispute_status`` must:

* emit a ``dispute.resolved`` transparency event on resolution to either
  RESOLVED_REEVAL or RESOLVED_STANDS
* enqueue a refresh row with ``trigger=DISPUTE`` only on RESOLVED_REEVAL

Triage transitions (e.g. → SUBSTANTIVE / → SPAM) MUST NOT emit or enqueue.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from smadp.config import Config
from smadp.refresh import queue as refresh_queue
from smadp.schemas.dispute import DisputeDecision, RequestedOutcome
from smadp.schemas.refresh import RefreshTrigger
from smadp.vendor import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    return Config()


def _file_dispute(cfg: Config) -> str:
    d = store.file_dispute(
        workspace_id="ws_TESTWS01",
        verdict_id="agent-a__agent-b",
        vendor_user_id="vendor-1",
        argument_md="x",
        requested_outcome=RequestedOutcome.REEVAL,
        config=cfg,
    )
    return d.id


def test_resolve_reeval_emits_transparency_and_enqueues_refresh(cfg: Config) -> None:
    dispute_id = _file_dispute(cfg)
    store.update_dispute_status(
        dispute_id=dispute_id,
        decision=DisputeDecision.SUBSTANTIVE,
        rationale_md=None,
        config=cfg,
    )
    with patch("smadp.vendor.store.append_event") as tx_mock:
        store.update_dispute_status(
            dispute_id=dispute_id,
            decision=DisputeDecision.REEVAL,
            rationale_md="reasonable challenge",
            config=cfg,
        )
    tx_mock.assert_called_once()
    kwargs = tx_mock.call_args.kwargs
    assert kwargs["event_type"] == "dispute.resolved"
    assert kwargs["payload"]["dispute_id"] == dispute_id
    assert kwargs["payload"]["decision"] == "reeval"

    pending = refresh_queue.list_pending(config=cfg)
    assert len(pending) == 1
    assert pending[0].verdict_id == "agent-a__agent-b"
    assert pending[0].trigger is RefreshTrigger.DISPUTE
    assert pending[0].trigger_detail.get("dispute_id") == dispute_id


def test_resolve_stands_emits_transparency_no_refresh(cfg: Config) -> None:
    dispute_id = _file_dispute(cfg)
    store.update_dispute_status(
        dispute_id=dispute_id,
        decision=DisputeDecision.SUBSTANTIVE,
        rationale_md=None,
        config=cfg,
    )
    with patch("smadp.vendor.store.append_event") as tx_mock:
        store.update_dispute_status(
            dispute_id=dispute_id,
            decision=DisputeDecision.STANDS,
            rationale_md="upheld",
            config=cfg,
        )
    tx_mock.assert_called_once()
    assert tx_mock.call_args.kwargs["event_type"] == "dispute.resolved"
    assert refresh_queue.list_pending(config=cfg) == []


def test_triage_does_not_emit_or_enqueue(cfg: Config) -> None:
    dispute_id = _file_dispute(cfg)
    with patch("smadp.vendor.store.append_event") as tx_mock:
        store.update_dispute_status(
            dispute_id=dispute_id,
            decision=DisputeDecision.SUBSTANTIVE,
            rationale_md=None,
            config=cfg,
        )
    tx_mock.assert_not_called()
    assert refresh_queue.list_pending(config=cfg) == []
