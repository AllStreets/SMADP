from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml  # type: ignore[import-untyped]


def load_priority(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text("utf-8")) or {}
    entries = raw.get("priority") or []
    return [
        {"scenario": e["scenario"], "agents": list(e["agents"])}
        for e in entries
        if isinstance(e, dict) and "scenario" in e and "agents" in e
    ]
