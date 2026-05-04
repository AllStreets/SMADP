"""Scoring-weights watcher (fixture-driven stub)."""

from __future__ import annotations

from smadp.refresh.watchers._fixture_base import FixtureWatcher
from smadp.schemas.refresh import RefreshTrigger


class ScoringWeightsWatcher(FixtureWatcher):
    trigger = RefreshTrigger.SCORING_WEIGHTS
    fixture_name = "scoring_weights"


__all__ = ["ScoringWeightsWatcher"]
