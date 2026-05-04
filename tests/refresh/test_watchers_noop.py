"""Tests for no-op watchers (manual, dispute) and the registry shape."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.refresh.watchers import iter_watchers
from smadp.refresh.watchers.dispute import DisputeWatcher
from smadp.refresh.watchers.manual import ManualWatcher
from smadp.schemas.refresh import RefreshTrigger


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    return Config()


def test_manual_watcher_returns_empty(cfg: Config) -> None:
    w = ManualWatcher()
    assert w.trigger is RefreshTrigger.MANUAL
    assert w.discover(config=cfg) == []


def test_dispute_watcher_returns_empty(cfg: Config) -> None:
    w = DisputeWatcher()
    assert w.trigger is RefreshTrigger.DISPUTE
    assert w.discover(config=cfg) == []


def test_iter_watchers_includes_manual_and_dispute() -> None:
    triggers = {w.trigger for w in iter_watchers()}
    assert RefreshTrigger.MANUAL in triggers
    assert RefreshTrigger.DISPUTE in triggers
