"""Manual-trigger watcher — always empty.

Manual refreshes are enqueued directly by the API/CLI; this watcher exists
so every ``RefreshTrigger`` value has a corresponding ``Watcher`` and the
sweep loop can be reasoned about uniformly.
"""

from __future__ import annotations

from typing import Any

from smadp.config import Config
from smadp.schemas.refresh import RefreshTrigger


class ManualWatcher:
    trigger = RefreshTrigger.MANUAL

    def discover(self, *, config: Config) -> list[tuple[str, dict[str, Any]]]:
        return []


__all__ = ["ManualWatcher"]
