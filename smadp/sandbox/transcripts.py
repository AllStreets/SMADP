"""Structured transcripts for sandbox runs.

A transcript is an append-only JSON Lines stream of events emitted while two
agents are interacting in the sandbox. Each event line is self-contained: it
identifies the agent, the I/O direction, a UTC timestamp, the event type, and
an opaque payload. Transcripts are the *evidence layer* that lets the catalog
either confirm or contradict an LLM-judged sub-verdict, so they must be:

* **Lossless** — write through to disk before any container operation that
  could crash the worker.
* **Tamper-evident downstream** — the catalog stores the transcript path and
  hashes its contents into the verdict bundle.
* **Schema-stable** — adding new event types is fine; renaming or removing
  existing ones is not.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from smadp.utils.time import utcnow

EventType = Literal[
    "start",
    "stdout",
    "stderr",
    "file_write",
    "file_read",
    "network_attempt",
    "tool_call",
    "exit",
    "policy_violation",
    "scenario_assertion",
]

Direction = Literal["agent_to_env", "env_to_agent", "internal"]


@dataclass(frozen=True)
class TranscriptEvent:
    """One line of a transcript JSONL file.

    ``payload`` is intentionally typed as ``dict[str, Any]`` so each event
    type can carry whatever structured detail is useful (we don't want to
    explode the schema with a class per event). The keys we *do* commit to
    are documented per-event-type below.

    Per-type payload conventions:

    * ``start``: ``{ "image_digest": str, "argv": list[str] }``
    * ``stdout`` / ``stderr``: ``{ "line": str }``  (one line per event)
    * ``file_write`` / ``file_read``: ``{ "path": str, "size": int }``
    * ``network_attempt``: ``{ "host": str, "port": int, "allowed": bool }``
    * ``tool_call``: ``{ "name": str, "args_redacted": dict }``
    * ``exit``: ``{ "code": int, "signal": int | None }``
    * ``policy_violation``: ``{ "kind": str, "detail": str }``
    * ``scenario_assertion``: ``{ "name": str, "passed": bool, "detail": str }``
    """

    agent: str
    direction: Direction
    ts: datetime
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    note: str | None = None

    def to_json_line(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        d = asdict(self)
        d["ts"] = self.ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json_line(cls, line: str) -> TranscriptEvent:
        d = json.loads(line)
        ts_raw = d.pop("ts")
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        return cls(ts=ts, **d)


@dataclass
class Transcript:
    """In-memory representation of a sandbox transcript.

    For long-running scenarios the runner writes events through a
    :class:`TranscriptWriter` directly to disk; this class is mainly for
    loading completed transcripts and for unit tests.
    """

    run_id: str
    path: Path
    events: list[TranscriptEvent] = field(default_factory=list)

    def append(self, event: TranscriptEvent) -> None:
        self.events.append(event)

    def to_jsonl(self) -> str:
        return "\n".join(e.to_json_line() for e in self.events) + ("\n" if self.events else "")

    @classmethod
    def from_jsonl(cls, run_id: str, path: Path, text: str) -> Transcript:
        events = [
            TranscriptEvent.from_json_line(line) for line in text.splitlines() if line.strip()
        ]
        return cls(run_id=run_id, path=path, events=events)

    @classmethod
    def load(cls, run_id: str, path: Path) -> Transcript:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return cls.from_jsonl(run_id, path, text)

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.to_jsonl(), encoding="utf-8")


class TranscriptWriter:
    """Streaming, append-only writer for transcripts.

    Each :meth:`emit` call flushes the underlying file handle so that a worker
    crash mid-run still leaves the partial transcript on disk. This is the
    write path the runner uses; :class:`Transcript` is the read path.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # ``a`` so re-opens (e.g. resume) don't truncate the audit trail.
        self._fh = self.path.open("a", encoding="utf-8")

    def emit(
        self,
        agent: str,
        event_type: EventType,
        *,
        direction: Direction = "internal",
        payload: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> TranscriptEvent:
        event = TranscriptEvent(
            agent=agent,
            direction=direction,
            ts=utcnow(),
            event_type=event_type,
            payload=payload or {},
            note=note,
        )
        self._fh.write(event.to_json_line() + "\n")
        self._fh.flush()
        return event

    def close(self) -> None:
        try:
            self._fh.flush()
        finally:
            self._fh.close()

    def __enter__(self) -> TranscriptWriter:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def iter_events(path: Path) -> Iterator[TranscriptEvent]:
    """Lazily iterate events from a transcript file."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield TranscriptEvent.from_json_line(line)


def filter_events(
    events: Iterable[TranscriptEvent],
    *,
    event_type: EventType | None = None,
    agent: str | None = None,
) -> list[TranscriptEvent]:
    out: list[TranscriptEvent] = []
    for e in events:
        if event_type is not None and e.event_type != event_type:
            continue
        if agent is not None and e.agent != agent:
            continue
        out.append(e)
    return out


__all__ = [
    "Direction",
    "EventType",
    "Transcript",
    "TranscriptEvent",
    "TranscriptWriter",
    "filter_events",
    "iter_events",
]
