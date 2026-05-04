"""Tests for smadp.refresh.queue — enqueue + list_pending."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.refresh import queue
from smadp.schemas.refresh import RefreshTrigger


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    return Config()


def test_enqueue_returns_row_and_is_listed(cfg: Config) -> None:
    item = queue.enqueue(
        verdict_id="a__b",
        trigger=RefreshTrigger.MANUAL,
        trigger_detail={"reason": "ops"},
        config=cfg,
    )
    assert item.id > 0
    assert item.verdict_id == "a__b"
    assert item.trigger is RefreshTrigger.MANUAL
    assert item.trigger_detail == {"reason": "ops"}
    assert item.claimed_at is None
    assert item.done_at is None

    pending = queue.list_pending(config=cfg)
    assert [p.id for p in pending] == [item.id]


def test_enqueue_preserves_fifo_order(cfg: Config) -> None:
    a = queue.enqueue(verdict_id="x__y", trigger=RefreshTrigger.TTL, config=cfg)
    b = queue.enqueue(verdict_id="y__z", trigger=RefreshTrigger.TTL, config=cfg)
    pending = queue.list_pending(config=cfg)
    assert [p.id for p in pending] == [a.id, b.id]
