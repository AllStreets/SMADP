"""Unit tests for smadp.schemas.dispute."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smadp.schemas.dispute import (
    Dispute,
    DisputeDecision,
    DisputeStatus,
    RequestedOutcome,
)


def test_dispute_status_values_locked():
    assert {s.value for s in DisputeStatus} == {
        "triage",
        "pending_review",
        "resolved_reeval",
        "resolved_stands",
        "spam",
    }


def test_requested_outcome_values_locked():
    assert {o.value for o in RequestedOutcome} == {"reeval", "withdraw", "amend"}


def test_dispute_decision_values_locked():
    assert {d.value for d in DisputeDecision} == {
        "spam",
        "substantive",
        "reeval",
        "stands",
    }


def test_dispute_id_pattern_enforced():
    with pytest.raises(ValidationError):
        Dispute(
            id="dsp_bad",
            workspace_id="ws_ABCD1234",
            verdict_id="vdt_X",
            vendor_user_id="user_a",
            argument_md="argument",
            requested_outcome=RequestedOutcome.REEVAL,
            status=DisputeStatus.TRIAGE,
            decision_rationale_md=None,
            filed_at=datetime.now(UTC),
            triaged_at=None,
            resolved_at=None,
            sla_breached_at=None,
        )


def test_dispute_argument_md_nonempty():
    with pytest.raises(ValidationError):
        Dispute(
            id="dsp_20260503120000_abcdef",
            workspace_id="ws_ABCD1234",
            verdict_id="vdt_X",
            vendor_user_id="user_a",
            argument_md="",
            requested_outcome=RequestedOutcome.REEVAL,
            status=DisputeStatus.TRIAGE,
            decision_rationale_md=None,
            filed_at=datetime.now(UTC),
            triaged_at=None,
            resolved_at=None,
            sla_breached_at=None,
        )
