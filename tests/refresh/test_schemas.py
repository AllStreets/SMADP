"""Tests for smadp.schemas.refresh."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from smadp.schemas.refresh import RefreshQueueItem, RefreshState, RefreshTrigger


def test_refresh_trigger_values() -> None:
    assert RefreshTrigger.MANUAL.value == "manual"
    assert RefreshTrigger.TTL.value == "ttl"
    assert RefreshTrigger.DISPUTE.value == "dispute"
    assert RefreshTrigger.REPO_RELEASE.value == "repo_release"
    assert RefreshTrigger.DEPENDENCY_CVE.value == "dependency_cve"
    assert RefreshTrigger.MODEL_BUMP.value == "model_bump"
    assert RefreshTrigger.FRAMEWORK_VERSION.value == "framework_version"
    assert RefreshTrigger.SCORING_WEIGHTS.value == "scoring_weights"
    assert RefreshTrigger.AGENT_CARD.value == "agent_card"
    # Exactly 9 values, no extras
    assert len(list(RefreshTrigger)) == 9


def test_refresh_queue_item_round_trip() -> None:
    item = RefreshQueueItem(
        id=1,
        verdict_id="agent-a__agent-b",
        trigger=RefreshTrigger.MANUAL,
        trigger_detail={"reason": "ops requested"},
        enqueued_at=datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc),
        claimed_at=None,
        done_at=None,
    )
    dumped = item.model_dump(mode="json")
    restored = RefreshQueueItem.model_validate(dumped)
    assert restored == item


def test_refresh_queue_item_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        RefreshQueueItem(
            id=1,
            verdict_id="a__b",
            trigger=RefreshTrigger.TTL,
            trigger_detail={},
            enqueued_at=datetime.now(timezone.utc),
            claimed_at=None,
            done_at=None,
            unexpected="boom",  # type: ignore[call-arg]
        )


def test_refresh_state_round_trip() -> None:
    state = RefreshState(
        verdict_id="a__b",
        last_trigger=RefreshTrigger.DISPUTE,
        last_evaluated_at=datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc),
        evaluation_count=3,
    )
    restored = RefreshState.model_validate(state.model_dump(mode="json"))
    assert restored == state
