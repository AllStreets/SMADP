"""In-process console event bus for live sandbox observation.

The runner emits every transcript event through a :class:`RunObservation`
(see Task 9) which, among other things, publishes a :class:`ConsoleEvent`
onto the process-local :data:`CONSOLE` bus. Subscribers (e.g. an in-process
live viewer, or the tripwire engine fed off the same emit path) drain a
per-run :class:`asyncio.Queue`.

The bus is purely in-process: the API server runs in a *separate* process and
relays the same observable stream by tailing the per-event-flushed transcript
JSONL (see ``smadp/api/routes/sandbox.py``). This module is the hot path the
worker uses to feed the tripwire engine.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from smadp.sandbox.transcripts import TranscriptEvent

# Map raw transcript event types to the coarser console "kind" surfaced to
# observers. stdout/stderr collapse to a single agent_output kind; lifecycle
# events (container start/exit) collapse to "lifecycle".
_TYPE_MAP: dict[str, str] = {
    "stdout": "agent_output",
    "stderr": "agent_output",
    "file_write": "file_write",
    "file_read": "file_read",
    "network_attempt": "network_attempt",
    "subprocess_spawn": "subprocess_spawn",
    "start": "lifecycle",
    "exit": "lifecycle",
    "tripwire": "tripwire",
    "policy_violation": "policy_violation",
    "scenario_assertion": "scenario_assertion",
    "tool_call": "tool_call",
}


def _iso_z(ts: datetime) -> str:
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ConsoleEvent:
    """One observable event on the live console bus."""

    run_id: str
    kind: str
    agent: str
    ts: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """JSON-serializable frame (ISO-Z timestamp)."""
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "agent": self.agent,
            "ts": _iso_z(self.ts),
            "payload": dict(self.payload),
        }


def to_console_event(run_id: str, event: TranscriptEvent) -> ConsoleEvent:
    """Project a transcript event onto a console event for live observers."""
    kind = _TYPE_MAP.get(event.event_type, event.event_type)
    return ConsoleEvent(
        run_id=run_id,
        kind=kind,
        agent=event.agent,
        ts=event.ts,
        payload=dict(event.payload),
    )


class RunConsole:
    """Per-run async fan-out bus.

    Each subscriber gets its own unbounded :class:`asyncio.Queue`; ``publish``
    pushes to every subscriber of the event's run only (other runs untouched).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[ConsoleEvent]]] = defaultdict(list)

    def subscribe(self, run_id: str) -> asyncio.Queue[ConsoleEvent]:
        q: asyncio.Queue[ConsoleEvent] = asyncio.Queue()
        self._subscribers[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[ConsoleEvent]) -> None:
        subs = self._subscribers.get(run_id)
        if not subs:
            return
        try:
            subs.remove(q)
        except ValueError:
            return
        if not subs:
            self._subscribers.pop(run_id, None)

    def publish(self, event: ConsoleEvent) -> None:
        for q in list(self._subscribers.get(event.run_id, ())):
            q.put_nowait(event)


# Process-local singleton bus the runner publishes through.
CONSOLE = RunConsole()


__all__ = [
    "CONSOLE",
    "ConsoleEvent",
    "RunConsole",
    "to_console_event",
]
