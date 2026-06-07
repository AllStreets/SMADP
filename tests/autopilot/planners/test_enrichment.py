"""Tests for EnrichmentPlanner."""

from __future__ import annotations

from smadp.autopilot.planners.enrichment import EnrichmentPlanner


def _profile(slug: str, score: float, level: str = "unverified-profile") -> dict:
    return {
        "slug": slug,
        "composite_score": score,
        "evidence_level": level,
        "onexus": {"source_github": f"x/{slug}"},
    }


def test_emits_one_item_per_unverified_profile() -> None:
    profiles = [_profile("a", 0.9), _profile("b", 0.7), _profile("c", 0.5)]
    planner = EnrichmentPlanner(top_n=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    slugs = sorted(i.pair[0] for i in items)
    assert slugs == ["a", "b", "c"]
    assert all(i.requested_judge == "profile_enrich" for i in items)


def test_skips_already_enriched_profiles() -> None:
    profiles = [
        _profile("a", 0.9, level="docs-only"),
        _profile("b", 0.7, level="unverified-profile"),
    ]
    planner = EnrichmentPlanner(top_n=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert {i.pair[0] for i in items} == {"b"}


def test_skips_profiles_without_github_source() -> None:
    profiles = [
        {
            "slug": "no-source",
            "composite_score": 0.9,
            "evidence_level": "unverified-profile",
            "onexus": {"source_github": None},
        },
        _profile("b", 0.7),
    ]
    planner = EnrichmentPlanner(top_n=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert {i.pair[0] for i in items} == {"b"}


def test_top_n_cap_keeps_highest_score() -> None:
    profiles = [_profile(s, score) for s, score in [("a", 0.9), ("b", 0.8), ("c", 0.1)]]
    planner = EnrichmentPlanner(top_n=2)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    slugs = {i.pair[0] for i in items}
    assert slugs == {"a", "b"}


def test_pair_uses_slug_slug_singleton() -> None:
    profiles = [_profile("a", 0.9)]
    planner = EnrichmentPlanner(top_n=10)
    items = planner.plan(profiles=profiles, now_iso="2026-06-06T00:00:00Z")
    assert items[0].pair == ("a", "a")
    assert items[0].priority == 0.9
