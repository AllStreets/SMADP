"""EnrichmentPlanner: one WorkItem per unverified-profile that needs enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from smadp.autopilot.work_queue import WorkItem


@dataclass(frozen=True)
class EnrichmentPlanner:
    top_n: int
    judge_name: str = "profile_enrich"
    judge_version: str = "v1"

    def plan(self, *, profiles: list[dict[str, Any]], now_iso: str) -> list[WorkItem]:
        eligible: list[dict[str, Any]] = []
        for p in profiles:
            if p.get("evidence_level") != "unverified-profile":
                continue
            github = (p.get("onexus") or {}).get("source_github")
            if not github:
                continue
            eligible.append(p)
        eligible.sort(key=lambda p: float(p.get("composite_score", 0.0)), reverse=True)
        eligible = eligible[: self.top_n]

        items: list[WorkItem] = []
        for p in eligible:
            slug = p["slug"]
            items.append(
                WorkItem(
                    pair=(slug, slug),
                    requested_judge=self.judge_name,
                    judge_version=self.judge_version,
                    priority=float(p.get("composite_score", 0.0)),
                    enqueued_at=now_iso,
                )
            )
        return items
