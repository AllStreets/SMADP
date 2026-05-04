"""Agent-card watcher (fixture-driven stub)."""

from __future__ import annotations

from smadp.refresh.watchers._fixture_base import FixtureWatcher
from smadp.schemas.refresh import RefreshTrigger


class AgentCardWatcher(FixtureWatcher):
    trigger = RefreshTrigger.AGENT_CARD
    fixture_name = "agent_card"


__all__ = ["AgentCardWatcher"]
