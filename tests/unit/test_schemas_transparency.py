"""Tests for transparency Pydantic schemas."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smadp.schemas.transparency import InclusionProof, SignedEvent


def test_signed_event_round_trip():
    ev = SignedEvent(
        id=1,
        event_type="verdict.created",
        payload={"verdict_id": "vdt_01"},
        ts=datetime(2026, 5, 3, tzinfo=UTC),
        prev_hash="sha256:" + "0" * 64,
        signature="aabbccdd",
        rekor_uuid=None,
    )
    assert ev.id == 1
    assert ev.payload["verdict_id"] == "vdt_01"
    dumped = ev.model_dump()
    SignedEvent.model_validate(dumped)


def test_signed_event_extra_forbidden():
    with pytest.raises(ValidationError):
        SignedEvent(
            id=1,
            event_type="x",
            payload={},
            ts=datetime(2026, 5, 3, tzinfo=UTC),
            prev_hash="sha256:" + "0" * 64,
            signature="aa",
            rekor_uuid=None,
            extra="boom",
        )


def test_signed_event_prev_hash_pattern():
    with pytest.raises(ValidationError):
        SignedEvent(
            id=1,
            event_type="x",
            payload={},
            ts=datetime(2026, 5, 3, tzinfo=UTC),
            prev_hash="not-a-hash",
            signature="aa",
            rekor_uuid=None,
        )


def test_inclusion_proof_minimal():
    p = InclusionProof(
        log_id=4827193,
        log_index=4827192,
        leaf_hash="sha256:" + "f" * 64,
        path=["sha256:" + "1" * 64, "sha256:" + "2" * 64],
    )
    assert p.log_index == 4827192
    assert len(p.path) == 2
