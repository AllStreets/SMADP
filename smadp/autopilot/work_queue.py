"""WorkItem dataclass + JSONL work queue used by the docs-only autopilot path.

Queue file format: one JSON object per line, sorted-pair canonical form.

Idempotency: appending a (pair, requested_judge, judge_version) tuple that
already exists in the file is a no-op. This makes bootstrap re-runnable.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkItem:
    pair: tuple[str, str]
    requested_judge: str
    judge_version: str
    priority: float
    enqueued_at: str

    def to_jsonable(self) -> dict:
        return {
            "pair": list(self.pair),
            "requested_judge": self.requested_judge,
            "judge_version": self.judge_version,
            "priority": self.priority,
            "enqueued_at": self.enqueued_at,
        }

    @classmethod
    def from_jsonable(cls, raw: dict) -> WorkItem:
        pair = tuple(sorted(raw["pair"]))
        return cls(
            pair=(pair[0], pair[1]),
            requested_judge=raw["requested_judge"],
            judge_version=raw["judge_version"],
            priority=float(raw["priority"]),
            enqueued_at=raw["enqueued_at"],
        )


def _canonical(item: WorkItem) -> WorkItem:
    pair = tuple(sorted(item.pair))
    return WorkItem(
        pair=(pair[0], pair[1]),
        requested_judge=item.requested_judge,
        judge_version=item.judge_version,
        priority=item.priority,
        enqueued_at=item.enqueued_at,
    )


def read_all_items(path: Path) -> list[WorkItem]:
    if not path.exists():
        return []
    items: list[WorkItem] = []
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        items.append(WorkItem.from_jsonable(json.loads(line)))
    return items


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _existing_keys(path: Path) -> set[tuple[tuple[str, str], str, str]]:
    keys: set[tuple[tuple[str, str], str, str]] = set()
    for item in read_all_items(path):
        keys.add((item.pair, item.requested_judge, item.judge_version))
    return keys


def append_items(path: Path, items: list[WorkItem]) -> None:
    seen = _existing_keys(path)
    additions: list[WorkItem] = []
    for raw in items:
        canon = _canonical(raw)
        key = (canon.pair, canon.requested_judge, canon.judge_version)
        if key in seen:
            continue
        seen.add(key)
        additions.append(canon)
    if not additions:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for item in additions:
            f.write(json.dumps(item.to_jsonable()) + "\n")


def drain_items(path: Path, *, limit: int) -> list[WorkItem]:
    items = read_all_items(path)
    if not items:
        return []
    items_sorted = sorted(items, key=lambda i: -i.priority)
    drained = items_sorted[:limit]
    remaining = items_sorted[limit:]
    if remaining:
        content = "\n".join(json.dumps(i.to_jsonable()) for i in remaining) + "\n"
    else:
        content = ""
    _atomic_write_text(path, content)
    return drained
