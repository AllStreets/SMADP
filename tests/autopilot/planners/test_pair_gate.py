"""Tests for PairGatePlanner."""

from __future__ import annotations

import pytest

from smadp.autopilot.planners.pair_gate import PairGatePlanner


def _p(slug: str, score: float, level: str = "docs-only") -> dict:
    return {"slug": slug, "composite_score": score, "evidence_level": level}


def test_emits_pair_only_when_both_sides_enriched() -> None:
    profiles = [_p("a", 0.9), _p("b", 0.8), _p("c", 0.7, level="unverified-profile")]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    pairs = {tuple(i.pair) for i in items}
    assert pairs == {("a", "b")}


def test_emits_no_items_when_no_pair_qualifies() -> None:
    profiles = [_p("a", 0.9, level="unverified-profile")]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items == []


def test_priority_is_score_product() -> None:
    profiles = [_p("a", 0.9), _p("b", 0.5)]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].priority == pytest.approx(0.45)


def test_pair_cap_keeps_highest_priority() -> None:
    profiles = [_p(s, score) for s, score in zip("abcde", [0.9, 0.8, 0.7, 0.6, 0.5])]
    planner = PairGatePlanner(top_n=5, pair_cap=3)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert len(items) == 3
    assert items[0].pair == ("a", "b")


def test_pair_judge_name_used() -> None:
    profiles = [_p("a", 0.9), _p("b", 0.8)]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].requested_judge == "docs_only"
