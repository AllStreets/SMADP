"""Repo-release watcher (fixture-driven stub for tests/dev)."""

from __future__ import annotations

from smadp.refresh.watchers._fixture_base import FixtureWatcher
from smadp.schemas.refresh import RefreshTrigger


class RepoReleaseWatcher(FixtureWatcher):
    trigger = RefreshTrigger.REPO_RELEASE
    fixture_name = "repo_release"


__all__ = ["RepoReleaseWatcher"]
