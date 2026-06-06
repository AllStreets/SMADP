"""Tests for TopNPlanner."""

from __future__ import annotations

import pytest

from smadp.autopilot.planners.top_n import TopNPlanner


def _profile(slug: str, score: float) -> dict:
    return {"slug": slug, "composite_score": score, "evidence_level": "docs-only"}


def test_emits_all_pairs_for_small_set() -> None:
    profiles = [
        _profile("a", 0.9),
        _profile("b", 0.8),
        _profile("c", 0.7),
    ]
    planner = TopNPlanner(top_n=10, pair_cap=10, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")

    pairs = {tuple(i.pair) for i in items}
    assert pairs == {("a", "b"), ("a", "c"), ("b", "c")}


def test_pairs_sorted_canonically() -> None:
    profiles = [_profile("zebra", 0.9), _profile("aider", 0.8)]
    planner = TopNPlanner(top_n=10, pair_cap=10, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].pair == ("aider", "zebra")


def test_top_n_filters_lowest_scores() -> None:
    profiles = [_profile(s, score) for s, score in [
        ("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.1)
    ]]
    planner = TopNPlanner(top_n=3, pair_cap=10, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    slugs_in_pairs = {s for i in items for s in i.pair}
    assert "d" not in slugs_in_pairs


def test_pair_cap_honored_by_priority() -> None:
    profiles = [_profile(s, s_score) for s, s_score in zip("abcdef", [0.9, 0.8, 0.7, 0.6, 0.5, 0.4])]
    # 6C2 = 15 possible pairs
    planner = TopNPlanner(top_n=6, pair_cap=5, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert len(items) == 5
    # highest-priority pair should be (a,b) — product 0.72
    assert items[0].pair == ("a", "b")
    # priorities must be descending
    priorities = [i.priority for i in items]
    assert priorities == sorted(priorities, reverse=True)


def test_priority_is_score_product() -> None:
    profiles = [_profile("a", 0.9), _profile("b", 0.5)]
    planner = TopNPlanner(top_n=10, pair_cap=10, judge_name="docs_only", judge_version="v1")
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].priority == pytest.approx(0.45)
