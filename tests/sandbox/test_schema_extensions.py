"""Schema + queue plumbing for halted outcomes, mode, and operator halt."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.sandbox import queue
from smadp.schemas.chronicle import ChronicleEvent
from smadp.schemas.verdict import SandboxRun


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))
    return Config()


TS = datetime(2026, 6, 12, tzinfo=UTC)


def test_sandbox_run_mode_default_and_tripwire_rule() -> None:
    run = SandboxRun(
        run_id="r1",
        started_at=TS,
        outcome="pass",
        transcript_ref="queue://run/r1",
    )
    assert run.mode == "cooperative"
    assert run.tripwire_rule is None


def test_sandbox_run_accepts_adversarial_mode_and_rule() -> None:
    run = SandboxRun(
        run_id="r1",
        started_at=TS,
        outcome="halted_by_tripwire",
        transcript_ref="queue://run/r1",
        mode="adversarial",
        tripwire_rule="planted_secret_in_output",
    )
    assert run.mode == "adversarial"
    assert run.tripwire_rule == "planted_secret_in_output"


@pytest.mark.parametrize("outcome", ["halted_by_tripwire", "halted_by_operator"])
def test_halted_outcomes_accepted(outcome: str) -> None:
    run = SandboxRun(
        run_id="r1",
        started_at=TS,
        outcome=outcome,  # type: ignore[arg-type]
        transcript_ref="queue://run/r1",
    )
    assert run.outcome == outcome


def test_chronicle_tripwire_halted_event_accepted() -> None:
    event = ChronicleEvent(ts=TS, event="sandbox.tripwire.halted", by="sandbox-worker")
    assert event.event == "sandbox.tripwire.halted"


def test_request_halt_sets_flag_then_terminal_then_unknown(tmp_config: Config) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=tmp_config
    )
    # Pending → accepted, flag set.
    assert queue.request_halt(run_id, config=tmp_config) is True
    row = queue.get_raw_row(run_id, config=tmp_config)
    assert row is not None and row["halt_requested"] == 1

    # Drive it terminal; a halt request is then refused.
    queue.mark_completed(
        run_id, outcome="pass", transcript_path="/dev/null", config=tmp_config
    )
    assert queue.request_halt(run_id, config=tmp_config) is False

    # Unknown run → KeyError.
    with pytest.raises(KeyError):
        queue.request_halt("no-such-run", config=tmp_config)


def test_get_run_status_mode_is_adversarial_for_adversarial_scenario(tmp_config: Config) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="secret_exfiltration", config=tmp_config
    )
    status = queue.get_run_status(run_id, config=tmp_config)
    assert status.mode == "adversarial"


def test_get_run_status_mode_is_cooperative_for_cooperative_scenario(tmp_config: Config) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=tmp_config
    )
    status = queue.get_run_status(run_id, config=tmp_config)
    assert status.mode == "cooperative"
