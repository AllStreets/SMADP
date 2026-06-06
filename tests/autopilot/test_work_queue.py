"""Tests for WorkItem dataclass and JSONL queue helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.autopilot.work_queue import (
    WorkItem,
    append_items,
    drain_items,
    read_all_items,
)


def _mk(pair: tuple[str, str], judge: str = "docs_only", priority: float = 0.5) -> WorkItem:
    return WorkItem(
        pair=pair,
        requested_judge=judge,
        judge_version="v1",
        priority=priority,
        enqueued_at="2026-06-06T00:00:00Z",
    )


def test_append_then_read_round_trip(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    append_items(queue, [_mk(("aider", "cursor"))])
    items = read_all_items(queue)
    assert len(items) == 1
    assert items[0].pair == ("aider", "cursor")
    assert items[0].requested_judge == "docs_only"
    assert items[0].judge_version == "v1"


def test_append_dedupes_by_pair_and_judge(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    append_items(queue, [_mk(("aider", "cursor"))])
    append_items(queue, [_mk(("aider", "cursor"))])  # dupe
    append_items(queue, [_mk(("aider", "cursor"), judge="sandbox")])  # different judge OK
    items = read_all_items(queue)
    pairs_and_judges = [(i.pair, i.requested_judge) for i in items]
    assert pairs_and_judges == [
        (("aider", "cursor"), "docs_only"),
        (("aider", "cursor"), "sandbox"),
    ]


def test_drain_removes_drained_items(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    append_items(
        queue,
        [
            _mk(("a", "b"), priority=0.9),
            _mk(("c", "d"), priority=0.5),
            _mk(("e", "f"), priority=0.1),
        ],
    )
    drained = drain_items(queue, limit=2)
    assert [i.pair for i in drained] == [("a", "b"), ("c", "d")]  # priority order
    remaining = read_all_items(queue)
    assert [i.pair for i in remaining] == [("e", "f")]


def test_drain_on_empty_queue_returns_empty(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    drained = drain_items(queue, limit=5)
    assert drained == []


def test_pair_is_always_sorted(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    append_items(queue, [_mk(("zebra", "aider"))])
    items = read_all_items(queue)
    assert items[0].pair == ("aider", "zebra")
