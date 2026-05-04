"""Tests for smadp.refresh.queue — enqueue + list_pending."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


def test_claim_returns_oldest_and_marks_claimed(cfg: Config) -> None:
    a = queue.enqueue(verdict_id="a__b", trigger=RefreshTrigger.TTL, config=cfg)
    queue.enqueue(verdict_id="c__d", trigger=RefreshTrigger.TTL, config=cfg)
    claimed = queue.claim(config=cfg)
    assert claimed is not None
    assert claimed.id == a.id
    assert claimed.claimed_at is not None


def test_claim_skips_already_claimed(cfg: Config) -> None:
    queue.enqueue(verdict_id="a__b", trigger=RefreshTrigger.TTL, config=cfg)
    queue.enqueue(verdict_id="c__d", trigger=RefreshTrigger.TTL, config=cfg)
    first = queue.claim(config=cfg)
    second = queue.claim(config=cfg)
    assert first is not None and second is not None
    assert first.id != second.id


def test_claim_returns_none_when_empty(cfg: Config) -> None:
    assert queue.claim(config=cfg) is None


def test_finalize_marks_done(cfg: Config) -> None:
    item = queue.enqueue(verdict_id="a__b", trigger=RefreshTrigger.MANUAL, config=cfg)
    queue.claim(config=cfg)
    queue.finalize(item_id=item.id, config=cfg)
    assert queue.list_pending(config=cfg) == []


def test_finalize_unknown_id_raises(cfg: Config) -> None:
    with pytest.raises(KeyError):
        queue.finalize(item_id=999, config=cfg)


def test_reap_stale_unclaims_old_leases(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    item = queue.enqueue(verdict_id="a__b", trigger=RefreshTrigger.TTL, config=cfg)
    queue.claim(config=cfg)
    # Forge a stale claim by direct UPDATE
    import sqlite3

    conn = sqlite3.connect(cfg.cache_dir / "refresh.db")
    stale = datetime.now(UTC) - timedelta(seconds=600)
    conn.execute(
        "UPDATE refresh_queue SET claimed_at = ? WHERE id = ?",
        (stale.isoformat(timespec="seconds").replace("+00:00", "Z"), item.id),
    )
    conn.commit()
    conn.close()

    reaped = queue.reap_stale(config=cfg)
    assert reaped == 1
    pending = queue.list_pending(config=cfg)
    assert pending and pending[0].id == item.id and pending[0].claimed_at is None


def test_reap_stale_leaves_fresh_claims(cfg: Config) -> None:
    queue.enqueue(verdict_id="a__b", trigger=RefreshTrigger.TTL, config=cfg)
    queue.claim(config=cfg)
    reaped = queue.reap_stale(config=cfg)
    assert reaped == 0
