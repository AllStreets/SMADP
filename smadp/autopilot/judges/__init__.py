"""Judge protocol shared by all autopilot judges.

A judge takes a :class:`WorkItem` plus a profile lookup and emits a verdict
dict + cost. The protocol lets the tick orchestrator dispatch by name
without importing each concrete judge type.
"""

from __future__ import annotations

from typing import Any, Protocol


class JudgeResultLike(Protocol):
    verdict: dict[str, Any]
    cost_usd: float


class Judge(Protocol):
    name: str
    cost_per_call_usd: float

    def evaluate(self, work: Any, *, profiles: dict[str, dict[str, Any]]) -> JudgeResultLike: ...
