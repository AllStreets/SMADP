"""Triage-aware pair planner re-ordering (order only; never publishes)."""

from __future__ import annotations

from smadp.analyzer.triage import Prediction, TriageModel
from smadp.autopilot.planners.pair_gate import PairGatePlanner

BASE_PROFILE = {
    "name": "X", "vendor": {"type": "company", "handle": "h"},
    "source_type": "open-source", "category": "coding",
    "verification": {"status": "verified", "verified_at": "2026-01-01T00:00:00Z",
                     "method": "manual-authoring"},
    "first_seen_at": "2026-01-01T00:00:00Z", "last_refreshed_at": "2026-01-01T00:00:00Z",
}


def _pdict(slug: str, score: float, **caps) -> dict:
    return {
        **BASE_PROFILE, "slug": slug, "composite_score": score,
        "evidence_level": "profile-verified", "capabilities": caps,
    }


class _StubTriage:
    """Routes by slug: 'risk-*' pairs are high+uncertain, 'safe-*' are safe+confident."""

    def predict(self, a, b) -> Prediction:  # noqa: ANN001
        if a.slug.startswith("risk") or b.slug.startswith("risk"):
            return Prediction(band="high", probabilities={}, uncertainty=0.9)
        return Prediction(band="safe", probabilities={}, uncertainty=0.0)


def test_triage_reorders_risky_above_safe():
    # Two pairs with IDENTICAL base composite priority so only triage breaks the tie.
    profiles = [
        _pdict("safe-aa", 0.5), _pdict("safe-bb", 0.5),
        _pdict("risk-aa", 0.5), _pdict("risk-bb", 0.5),
    ]
    planner = PairGatePlanner(top_n=10, pair_cap=10, triage=_StubTriage())
    items = planner.plan(profiles=profiles, now_iso="2026-01-01T00:00:00Z")

    def _is_risky(pair):
        return any(s.startswith("risk") for s in pair)

    risky_rank = next(i for i, it in enumerate(items) if _is_risky(it.pair))
    safe_pair_rank = next(
        i for i, it in enumerate(items)
        if it.pair == ("safe-aa", "safe-bb")
    )
    assert risky_rank < safe_pair_rank


def test_baseline_without_triage_unchanged():
    profiles = [
        _pdict("aa", 0.9), _pdict("bb", 0.8), _pdict("cc", 0.1),
    ]
    planner = PairGatePlanner(top_n=10, pair_cap=10)
    items = planner.plan(profiles=profiles, now_iso="2026-01-01T00:00:00Z")
    # highest composite product first: aa*bb = 0.72 ranks above aa*cc / bb*cc.
    assert items[0].pair == ("aa", "bb")


def test_triage_accepts_real_model_without_crash():
    profiles = [_pdict("aa", 0.5), _pdict("bb", 0.5)]
    model = TriageModel(weights={}, bias={}, classes=[], majority_band="safe")
    planner = PairGatePlanner(top_n=10, pair_cap=10, triage=model)
    items = planner.plan(profiles=profiles, now_iso="2026-01-01T00:00:00Z")
    assert len(items) == 1
