"""Integration tests for the smadp webhook CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from smadp.cli import cli
from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.schemas.webhooks import EventType
from smadp.tenancy import store as tenancy
from smadp.webhooks import dispatcher, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="CLI", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_subscriptions_create_and_ls(cfg: Config, workspace_id: str):
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "webhook",
            "subscriptions",
            "create",
            "--workspace",
            workspace_id,
            "--url",
            "https://example.com/wh",
            "--event",
            "passport.generated",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "sub_" in res.output
    assert "secret:" in res.output  # secret printed once

    ls = runner.invoke(cli, ["webhook", "subscriptions", "ls", "--workspace", workspace_id])
    assert ls.exit_code == 0, ls.output
    assert "https://example.com/wh" in ls.output


def test_subscriptions_delete(cfg: Config, workspace_id: str):
    sub, _ = store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    runner = CliRunner()
    res = runner.invoke(cli, ["webhook", "subscriptions", "delete", sub.id])
    assert res.exit_code == 0, res.output


def test_deliveries_ls_shows_pending_rows(cfg: Config, workspace_id: str):
    store.create_subscription(
        workspace_id=workspace_id,
        url="https://example.com/wh",
        event_types=[EventType.PASSPORT_GENERATED],
        config=cfg,
    )
    dispatcher.dispatch_event(
        event_type=EventType.PASSPORT_GENERATED,
        payload={"verdict_id": "vdt_X"},
        workspace_id=workspace_id,
        signature_meta={"transparency_log_id": 1},
        config=cfg,
    )
    runner = CliRunner()
    res = runner.invoke(cli, ["webhook", "deliveries", "ls"])
    assert res.exit_code == 0, res.output
    assert "pending" in res.output
    assert "passport.generated" in res.output


def test_worker_once_no_pending_exits_zero(cfg: Config):
    runner = CliRunner()
    res = runner.invoke(cli, ["webhook", "worker", "--once"])
    assert res.exit_code == 0
    assert "no pending deliveries" in res.output.lower()
