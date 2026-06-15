"""PairGatePlanner: emit pair-judge WorkItems only when both sides enriched."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

from smadp.analyzer.triage import TriageModel
from smadp.autopilot.planners.triage_order import triage_urgency
from smadp.autopilot.work_queue import WorkItem

_ENRICHED_TIERS = {"docs-only", "behavior-observed", "profile-verified", "sandbox-validated"}


@dataclass(frozen=True)
class PairGatePlanner:
    top_n: int
    pair_cap: int
    judge_name: str = "docs_only"
    judge_version: str = "v1"
    # S2.3 optional triage re-ordering. When set, the base composite-product
    # priority is scaled by the pair's triage urgency so high-confidence-safe
    # pairs sink and uncertain/risky pairs float up. Triage NEVER writes a
    # verdict and never changes eligibility — only order.
    triage: TriageModel | None = None

    def plan(self, *, profiles: list[dict[str, Any]], now_iso: str) -> list[WorkItem]:
        enriched = [p for p in profiles if p.get("evidence_level") in _ENRICHED_TIERS]
        enriched.sort(key=lambda p: float(p.get("composite_score", 0.0)), reverse=True)
        enriched = enriched[: self.top_n]

        items: list[WorkItem] = []
        for p1, p2 in combinations(enriched, 2):
            a, b = sorted([p1["slug"], p2["slug"]])
            priority = float(p1.get("composite_score", 0.0)) * float(p2.get("composite_score", 0.0))
            if self.triage is not None:
                priority *= triage_urgency(self.triage, p1, p2)
            items.append(
                WorkItem(
                    pair=(a, b),
                    requested_judge=self.judge_name,
                    judge_version=self.judge_version,
                    priority=priority,
                    enqueued_at=now_iso,
                )
            )
        items.sort(key=lambda i: -i.priority)
        return items[: self.pair_cap]
