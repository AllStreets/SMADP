"""Tests for the smadp refresh Click subgroup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from smadp.config import Config
from smadp.refresh import queue
from smadp.refresh.cli import refresh_group
from smadp.schemas.refresh import RefreshTrigger


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config()
    monkeypatch.setattr("smadp.refresh.cli.load_config", lambda: cfg)
    return cfg


def test_enqueue_command(cfg: Config) -> None:
    r = CliRunner().invoke(
        refresh_group,
        ["enqueue", "--verdict-id", "a__b", "--reason", "ops"],
    )
    assert r.exit_code == 0, r.output
    assert "enqueued" in r.output
    assert queue.list_pending(config=cfg)


def test_ls_command(cfg: Config) -> None:
    queue.enqueue(verdict_id="a__b", trigger=RefreshTrigger.TTL, config=cfg)
    r = CliRunner().invoke(refresh_group, ["ls"])
    assert r.exit_code == 0
    assert "a__b" in r.output


def test_drain_command_invokes_evaluator(cfg: Config) -> None:
    with patch("smadp.refresh.cli.evaluator.drain_one", return_value=None) as m:
        r = CliRunner().invoke(refresh_group, ["drain"])
    assert r.exit_code == 0
    m.assert_called_once()
