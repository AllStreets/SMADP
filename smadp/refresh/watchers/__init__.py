"""Refresh watchers package — populated in Plan 5 Task 13+.

This minimal stub exists so ``smadp.refresh.poller`` can import
``iter_watchers`` ahead of the watcher protocol implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def iter_watchers() -> Iterable[Any]:
    """Yield each registered watcher instance (empty until Task 13)."""
    return ()


__all__ = ["iter_watchers"]
