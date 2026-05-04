"""Dispute-trigger watcher — always empty.

Dispute-driven refreshes are enqueued by the vendor store retrofit when a
dispute resolves (Plan 5 Task 18). This watcher exists so every
``RefreshTrigger`` has a corresponding ``Watcher`` registered in the sweep.
"""

from __future__ import annotations

from typing import Any

from smadp.config import Config
from smadp.schemas.refresh import RefreshTrigger


class DisputeWatcher:
    trigger = RefreshTrigger.DISPUTE

    def discover(self, *, config: Config) -> list[tuple[str, dict[str, Any]]]:
        return []


__all__ = ["DisputeWatcher"]
