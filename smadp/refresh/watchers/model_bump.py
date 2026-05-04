"""Model-bump watcher (fixture-driven stub)."""

from __future__ import annotations

from smadp.refresh.watchers._fixture_base import FixtureWatcher
from smadp.schemas.refresh import RefreshTrigger


class ModelBumpWatcher(FixtureWatcher):
    trigger = RefreshTrigger.MODEL_BUMP
    fixture_name = "model_bump"


__all__ = ["ModelBumpWatcher"]
