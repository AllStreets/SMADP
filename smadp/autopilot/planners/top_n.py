"""TopNPlanner: pick top-N profiles by composite_score, emit all-pair WorkItems."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from smadp.autopilot.work_queue import WorkItem


@dataclass(frozen=True)
class TopNPlanner:
    top_n: int
    pair_cap: int
    judge_name: str
    judge_version: str

    def plan(self, *, profiles: list[dict], now_iso: str) -> list[WorkItem]:
        scored = sorted(
            profiles,
            key=lambda p: float(p.get("composite_score", 0.0)),
            reverse=True,
        )[: self.top_n]

        items: list[WorkItem] = []
        for p1, p2 in combinations(scored, 2):
            slugs = tuple(sorted([p1["slug"], p2["slug"]]))
            priority = float(p1["composite_score"]) * float(p2["composite_score"])
            items.append(
                WorkItem(
                    pair=(slugs[0], slugs[1]),
                    requested_judge=self.judge_name,
                    judge_version=self.judge_version,
                    priority=priority,
                    enqueued_at=now_iso,
                )
            )
        items.sort(key=lambda i: -i.priority)
        return items[: self.pair_cap]
