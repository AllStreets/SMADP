from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key(scenario: str, participants: list[str]) -> tuple[str, tuple[str, ...]]:
    return (scenario, tuple(sorted(participants)))


def load_coverage(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"entries": []}
    data: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return data


def save_coverage(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record_enqueued(path: Path, *, scenario: str, participants: list[str]) -> None:
    payload = load_coverage(path)
    payload["entries"].append(
        {
            "scenario": scenario,
            "participants": sorted(participants),
            "enqueued_at": _now(),
        }
    )
    save_coverage(path, payload)


def has_recent_enqueue(path: Path, *, scenario: str, participants: list[str]) -> bool:
    """True if this scenario+participants pair has been enqueued in this state file."""
    target = _key(scenario, participants)
    for entry in load_coverage(path)["entries"]:
        if _key(entry["scenario"], entry["participants"]) == target:
            return True
    return False
