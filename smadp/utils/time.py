"""Time helpers — always UTC, ISO-8601."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
