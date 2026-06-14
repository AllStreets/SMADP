"""CLI: smadp sandbox watch + smadp sandbox halt."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from smadp.cli import cli
from smadp.config import Config
from smadp.sandbox import queue
from smadp.sandbox.runner import transcript_path_for
from smadp.sandbox.transcripts import TranscriptWriter


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    seed = Path(__file__).resolve().parents[2] / "catalog"
    shutil.copytree(seed, catalog)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


def _completed_run(cfg: Config) -> str:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=cfg
    )
    path = transcript_path_for(run_id, config=cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    w = TranscriptWriter(path)
    w.emit(
        agent=f"smadp-{run_id}-calendar",
        event_type="stdout",
        direction="agent_to_env",
        payload={"line": "hello-from-calendar"},
    )
    w.emit(
        agent=f"smadp-{run_id}-email",
        event_type="exit",
        direction="internal",
        payload={"code": 0},
    )
    w.close()
    queue.mark_completed(run_id, outcome="pass", transcript_path=str(path), config=cfg)
    return run_id


def test_watch_completed_run_prints_lines_and_outcome(env: Config) -> None:
    run_id = _completed_run(env)
    r = CliRunner().invoke(cli, ["sandbox", "watch", run_id])
    assert r.exit_code == 0, r.output
    assert "hello-from-calendar" in r.output
    assert "outcome=pass" in r.output


def test_watch_unknown_run_exits_2(env: Config) -> None:
    r = CliRunner().invoke(cli, ["sandbox", "watch", "no-such-run"])
    assert r.exit_code == 2


def test_halt_pending_run_sets_flag(env: Config) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=env
    )
    r = CliRunner().invoke(cli, ["sandbox", "halt", run_id])
    assert r.exit_code == 0, r.output
    row = queue.get_raw_row(run_id, config=env)
    assert row is not None and row["halt_requested"] == 1


def test_halt_terminal_run_exits_2(env: Config) -> None:
    run_id = _completed_run(env)
    r = CliRunner().invoke(cli, ["sandbox", "halt", run_id])
    assert r.exit_code == 2


def test_halt_unknown_run_exits_2(env: Config) -> None:
    r = CliRunner().invoke(cli, ["sandbox", "halt", "no-such-run"])
    assert r.exit_code == 2
