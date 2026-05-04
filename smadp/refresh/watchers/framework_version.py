"""Framework-version watcher (fixture-driven stub)."""

from __future__ import annotations

from smadp.refresh.watchers._fixture_base import FixtureWatcher
from smadp.schemas.refresh import RefreshTrigger


class FrameworkVersionWatcher(FixtureWatcher):
    trigger = RefreshTrigger.FRAMEWORK_VERSION
    fixture_name = "framework_version"


__all__ = ["FrameworkVersionWatcher"]
