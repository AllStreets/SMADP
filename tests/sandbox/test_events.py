"""In-process console event bus + ConsoleEvent mapping."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from smadp.sandbox.events import (
    CONSOLE,
    RunConsole,
    to_console_event,
)
from smadp.sandbox.transcripts import TranscriptEvent

TS = datetime(2026, 6, 12, tzinfo=UTC)


def _event(etype: str) -> TranscriptEvent:
    return TranscriptEvent(
        agent="smadp-r1-attacker",
        direction="agent_to_env",
        ts=TS,
        event_type=etype,  # type: ignore[arg-type]
        payload={"line": "x"},
    )


@pytest.mark.parametrize(
    ("etype", "expected"),
    [
        ("stdout", "agent_output"),
        ("stderr", "agent_output"),
        ("file_write", "file_write"),
        ("network_attempt", "network_attempt"),
        ("subprocess_spawn", "subprocess_spawn"),
        ("start", "lifecycle"),
        ("exit", "lifecycle"),
        ("tripwire", "tripwire"),
    ],
)
def test_to_console_event_type_map(etype: str, expected: str) -> None:
    ce = to_console_event("r1", _event(etype))
    assert ce.run_id == "r1"
    assert ce.kind == expected
    assert ce.agent == "smadp-r1-attacker"


def test_console_event_to_payload_iso_z() -> None:
    ce = to_console_event("r1", _event("stdout"))
    payload = ce.to_payload()
    assert payload["run_id"] == "r1"
    assert payload["kind"] == "agent_output"
    assert payload["ts"].endswith("Z")
    assert payload["payload"] == {"line": "x"}


def test_module_singleton_is_runconsole() -> None:
    assert isinstance(CONSOLE, RunConsole)


def test_subscribe_publish_unsubscribe_fans_out_per_run() -> None:
    async def _run() -> None:
        console = RunConsole()
        q1 = console.subscribe("r1")
        q2 = console.subscribe("r1")
        q_other = console.subscribe("r2")

        ce = to_console_event("r1", _event("stdout"))
        console.publish(ce)

        got1 = await asyncio.wait_for(q1.get(), timeout=1)
        got2 = await asyncio.wait_for(q2.get(), timeout=1)
        assert got1 is ce
        assert got2 is ce
        assert q_other.empty()

        console.unsubscribe("r1", q1)
        console.publish(to_console_event("r1", _event("stderr")))
        got2b = await asyncio.wait_for(q2.get(), timeout=1)
        assert got2b.kind == "agent_output"
        assert q1.empty()

    asyncio.run(_run())


def test_publish_to_no_subscribers_is_noop() -> None:
    console = RunConsole()
    console.publish(to_console_event("nobody", _event("stdout")))


def test_unsubscribe_unknown_is_safe() -> None:
    console = RunConsole()

    async def _run() -> None:
        q = console.subscribe("r1")
        console.unsubscribe("r1", q)
        console.unsubscribe("r1", q)  # double unsubscribe is safe
        console.unsubscribe("nope", q)  # unknown run is safe

    asyncio.run(_run())
