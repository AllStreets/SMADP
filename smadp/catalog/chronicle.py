"""Append-only audit log: file-per-day JSONL under `_chronicle/`.

Every mutation to the catalog SHOULD produce a chronicle entry. Writes are
durable: each append flushes to disk and fsyncs the file descriptor before
returning, and chronicle files are opened in line-buffered append mode so
concurrent appenders won't tear each other's records.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from smadp.config import Config, load_config
from smadp.schemas import ChronicleEvent
from smadp.utils.time import utcnow


class Chronicle:
    """Append-only event log."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self._lock = Lock()

    # ------------------------------------------------------------------ paths
    def _file_for(self, ts: datetime) -> Path:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_utc = ts.astimezone(timezone.utc)
        date_str = ts_utc.strftime("%Y-%m-%d")
        return self.config.chronicle_dir / f"{date_str}.jsonl"

    def _all_files(self) -> list[Path]:
        if not self.config.chronicle_dir.exists():
            return []
        return sorted(self.config.chronicle_dir.glob("*.jsonl"))

    # ------------------------------------------------------------------ write
    def append(self, event: ChronicleEvent) -> Path:
        """Append an event to the daily chronicle file. Returns the file path."""
        path = self._file_for(event.ts)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            event.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        with self._lock:
            # O_APPEND is atomic for writes <= PIPE_BUF on POSIX, which is
            # comfortably more than a single chronicle line.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        return path

    # ------------------------------------------------------------------- read
    def iter_events(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Iterator[ChronicleEvent]:
        for path in self._all_files():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for raw in fh:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            obj = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        try:
                            event = ChronicleEvent.model_validate(obj)
                        except ValueError:
                            continue
                        if since is not None and event.ts < _ensure_aware(since):
                            continue
                        if until is not None and event.ts > _ensure_aware(until):
                            continue
                        yield event
            except OSError:
                continue

    def tail(self, limit: int = 100) -> list[ChronicleEvent]:
        events = list(self.iter_events())
        events.sort(key=lambda e: e.ts)
        if limit > 0:
            return events[-limit:]
        return events

    # ----------------------------------------------------------------- record
    def record(
        self,
        event_type: str,
        *,
        by: str = "smadp",
        slug: str | None = None,
        pair: tuple[str, str] | None = None,
        verdict_id: str | None = None,
        model: str | None = None,
        outcome: str | None = None,
        details: dict[str, object] | None = None,
    ) -> Path:
        """Convenience wrapper around append() that builds the event for you."""
        event = ChronicleEvent(
            ts=utcnow(),
            event=event_type,  # type: ignore[arg-type]
            by=by,
            slug=slug,
            pair=pair,
            verdict_id=verdict_id,
            model=model,
            outcome=outcome,
            details=details or {},
        )
        return self.append(event)


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
