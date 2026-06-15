"""Runner observation wiring + tripwire/operator halt teardown."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.sandbox.events import CONSOLE, RunConsole, RunObservation
from smadp.sandbox.runner import _halt_watcher, transcript_path_for
from smadp.sandbox.tripwire import TripwireContext
from smadp.sandbox.transcripts import Transcript, TranscriptWriter


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))
    return Config()


SECRET = "synthetic-test-only-canary-abc"


def _ctx() -> TripwireContext:
    return TripwireContext(
        allow_egress=("api.openai.com",),
        secret_values=(SECRET,),
        expected_subprocesses=("python",),
    )


class _FakeProc:
    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def _obs(tmp_path: Path, mode: str, console: RunConsole) -> tuple[RunObservation, Path]:
    path = tmp_path / "transcript.jsonl"
    writer = TranscriptWriter(path)
    obs = RunObservation(
        run_id="r1",
        writer=writer,
        console=console,
        tripwire_ctx=_ctx(),
        tripwire_mode=mode,
    )
    return obs, path


def test_enabled_secret_emit_sets_halt_and_records_and_publishes(tmp_path: Path) -> None:
    async def _run() -> None:
        console = RunConsole()
        q = console.subscribe("r1")
        obs, path = _obs(tmp_path, "enabled", console)

        obs.emit(
            agent="smadp-r1-attacker",
            event_type="stdout",
            direction="agent_to_env",
            payload={"line": f"leak {SECRET}"},
        )

        assert obs.halt_event.is_set()
        assert obs.halted is True
        assert obs.tripwire_rule == "planted_secret_in_output"

        # transcript holds the agent_output AND the tripwire event.
        obs.writer.close()
        tr = Transcript.load("r1", path)
        types = [e.event_type for e in tr.events]
        assert "stdout" in types
        assert "tripwire" in types

        # console saw agent_output then tripwire.
        first = await asyncio.wait_for(q.get(), timeout=1)
        second = await asyncio.wait_for(q.get(), timeout=1)
        assert first.kind == "agent_output"
        assert second.kind == "tripwire"

    asyncio.run(_run())


def test_log_only_records_tripwire_without_halt(tmp_path: Path) -> None:
    console = RunConsole()
    obs, path = _obs(tmp_path, "log_only", console)
    obs.emit(
        agent="smadp-r1-attacker",
        event_type="stdout",
        direction="agent_to_env",
        payload={"line": SECRET},
    )
    assert not obs.halt_event.is_set()
    assert obs.halted is False
    obs.writer.close()
    tr = Transcript.load("r1", path)
    trips = [e for e in tr.events if e.event_type == "tripwire"]
    assert len(trips) == 1
    assert trips[0].payload.get("mode") == "log_only"


def test_off_never_checks(tmp_path: Path) -> None:
    console = RunConsole()
    obs, path = _obs(tmp_path, "off", console)
    obs.emit(
        agent="smadp-r1-attacker",
        event_type="stdout",
        direction="agent_to_env",
        payload={"line": SECRET},
    )
    assert not obs.halt_event.is_set()
    obs.writer.close()
    tr = Transcript.load("r1", path)
    assert not any(e.event_type == "tripwire" for e in tr.events)


def test_halt_watcher_kills_processes_and_engine_kills(tmp_path: Path) -> None:
    async def _run() -> None:
        console = RunConsole()
        obs, _ = _obs(tmp_path, "enabled", console)
        p1 = _FakeProc()
        p2 = _FakeProc()
        obs.register_process("smadp-r1-attacker", p1)
        obs.register_process("smadp-r1-victim", p2)

        killed_names: list[str] = []

        def _engine_kill(name: str) -> None:
            killed_names.append(name)

        watcher = asyncio.create_task(_halt_watcher(obs, engine_kill=_engine_kill))
        await asyncio.sleep(0)
        obs.trip_operator_halt()
        await asyncio.wait_for(watcher, timeout=2)

        assert p1.killed and p2.killed
        assert sorted(killed_names) == ["smadp-r1-attacker", "smadp-r1-victim"]
        obs.writer.close()

    asyncio.run(_run())


def test_transcript_path_for_is_pure(tmp_config: Config) -> None:
    p = transcript_path_for("sb_unmade_run", config=tmp_config)
    assert p.name == "transcript.jsonl"
    # Pure: no directory created as a side effect.
    assert not p.parent.exists()


def test_module_console_singleton_default(tmp_path: Path) -> None:
    # RunObservation defaults to the module CONSOLE when none is passed.
    path = tmp_path / "transcript.jsonl"
    writer = TranscriptWriter(path)
    obs = RunObservation(
        run_id="rX", writer=writer, tripwire_ctx=_ctx(), tripwire_mode="off"
    )
    assert obs.console is CONSOLE
    writer.close()
