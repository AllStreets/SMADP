"""Dependency-CVE watcher (fixture-driven stub)."""

from __future__ import annotations

from smadp.refresh.watchers._fixture_base import FixtureWatcher
from smadp.schemas.refresh import RefreshTrigger


class DependencyCveWatcher(FixtureWatcher):
    trigger = RefreshTrigger.DEPENDENCY_CVE
    fixture_name = "dependency_cve"


__all__ = ["DependencyCveWatcher"]
