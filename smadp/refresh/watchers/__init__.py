"""Refresh watchers — one per RefreshTrigger value.

Each watcher exposes:

* ``trigger: RefreshTrigger`` (class attr)
* ``discover(*, config) -> list[tuple[str, dict]]`` — verdict_ids to enqueue
  paired with trigger_detail dicts.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from smadp.config import Config
from smadp.schemas.refresh import RefreshTrigger


class Watcher(Protocol):
    trigger: RefreshTrigger

    def discover(self, *, config: Config) -> list[tuple[str, dict[str, Any]]]: ...


def iter_watchers() -> Iterable[Watcher]:
    """Return every registered watcher instance.

    Imports are lazy so a missing watcher module (e.g., during
    incremental Plan 5 task landings) does not break callers that only
    need a subset.
    """
    from smadp.refresh.watchers.dispute import DisputeWatcher
    from smadp.refresh.watchers.manual import ManualWatcher

    watchers: list[Watcher] = [ManualWatcher(), DisputeWatcher()]

    # The remaining 7 watchers come online in Tasks 14-15. Import them
    # if available so iter_watchers naturally grows as those tasks land.
    optional_modules = (
        ("smadp.refresh.watchers.ttl", "TtlWatcher"),
        ("smadp.refresh.watchers.repo_release", "RepoReleaseWatcher"),
        ("smadp.refresh.watchers.dependency_cve", "DependencyCveWatcher"),
        ("smadp.refresh.watchers.model_bump", "ModelBumpWatcher"),
        ("smadp.refresh.watchers.framework_version", "FrameworkVersionWatcher"),
        ("smadp.refresh.watchers.scoring_weights", "ScoringWeightsWatcher"),
        ("smadp.refresh.watchers.agent_card", "AgentCardWatcher"),
    )
    for mod_name, cls_name in optional_modules:
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
        except ImportError:
            continue
        watchers.append(getattr(mod, cls_name)())
    return watchers


__all__ = ["Watcher", "iter_watchers"]
