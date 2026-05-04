"""Tests for smadp.refresh.poller — sweep loop entry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from smadp.config import Config
from smadp.refresh import poller, queue
from smadp.schemas.refresh import RefreshTrigger


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    return Config()


def test_sweep_invokes_each_watcher(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_watcher = MagicMock()
    fake_watcher.trigger = RefreshTrigger.TTL
    fake_watcher.discover.return_value = [("a__b", {"reason": "expired"})]

    monkeypatch.setattr(poller, "iter_watchers", lambda: [fake_watcher])
    poller.sweep(config=cfg)

    fake_watcher.discover.assert_called_once()
    pending = queue.list_pending(config=cfg)
    assert [p.verdict_id for p in pending] == ["a__b"]
    assert pending[0].trigger is RefreshTrigger.TTL


def test_sweep_dedupes_same_verdict(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = MagicMock()
    w.trigger = RefreshTrigger.TTL
    w.discover.return_value = [("a__b", {})]
    monkeypatch.setattr(poller, "iter_watchers", lambda: [w])
    poller.sweep(config=cfg)
    poller.sweep(config=cfg)
    pending = queue.list_pending(config=cfg)
    assert len(pending) == 1
