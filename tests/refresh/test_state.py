"""Tests for smadp.refresh.state — per-verdict refresh tracking table."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.refresh import state
from smadp.schemas.refresh import RefreshTrigger


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    return Config()


def test_get_state_returns_none_when_unknown(cfg: Config) -> None:
    assert state.get_state(verdict_id="a__b", config=cfg) is None


def test_upsert_then_get(cfg: Config) -> None:
    when = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state.upsert_state(
        verdict_id="a__b",
        trigger=RefreshTrigger.MANUAL,
        evaluated_at=when,
        config=cfg,
    )
    s = state.get_state(verdict_id="a__b", config=cfg)
    assert s is not None
    assert s.verdict_id == "a__b"
    assert s.last_trigger is RefreshTrigger.MANUAL
    assert s.last_evaluated_at == when
    assert s.evaluation_count == 1


def test_upsert_increments_count(cfg: Config) -> None:
    when = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    later = datetime(2026, 5, 3, 13, 0, tzinfo=timezone.utc)
    state.upsert_state(
        verdict_id="a__b", trigger=RefreshTrigger.TTL, evaluated_at=when, config=cfg
    )
    state.upsert_state(
        verdict_id="a__b", trigger=RefreshTrigger.DISPUTE, evaluated_at=later, config=cfg
    )
    s = state.get_state(verdict_id="a__b", config=cfg)
    assert s is not None
    assert s.last_trigger is RefreshTrigger.DISPUTE
    assert s.last_evaluated_at == later
    assert s.evaluation_count == 2
