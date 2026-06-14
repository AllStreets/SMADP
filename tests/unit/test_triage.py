from __future__ import annotations

import pytest

from smadp.analyzer.triage import (
    FEATURE_NAMES,
    TriageModel,
    band_for_composite,
    featurize,
    train,
)
from smadp.schemas.profile import Profile

BASE = {
    "slug": "demo-agent", "name": "Demo",
    "vendor": {"type": "company", "handle": "acme"},
    "source_type": "open-source", "category": "coding",
    "verification": {"status": "verified", "verified_at": "2026-01-01T00:00:00Z",
                     "method": "manual-authoring"},
    "first_seen_at": "2026-01-01T00:00:00Z", "last_refreshed_at": "2026-01-01T00:00:00Z",
}


def _profile(slug: str, category: str = "coding", **caps) -> Profile:
    return Profile.model_validate(
        {**BASE, "slug": slug, "category": category, "capabilities": caps}
    )


@pytest.fixture
def profile_a() -> Profile:
    return _profile("agent-aa", execute_shell=True, network_egress="broad")


@pytest.fixture
def profile_b() -> Profile:
    return _profile("agent-bb", read_filesystem=True, network_egress="allowlisted")


def _safe(slug_a: str, slug_b: str) -> tuple[Profile, Profile, float]:
    return (_profile(slug_a, "writing"), _profile(slug_b, "writing"), 0.05)


def _risky(slug_a: str, slug_b: str) -> tuple[Profile, Profile, float]:
    return (
        _profile(slug_a, "coding", execute_shell=True, network_egress="broad"),
        _profile(slug_b, "coding", write_filesystem=True, modify_git_state=True),
        0.85,
    )


@pytest.fixture
def tiny_corpus() -> list[tuple[Profile, Profile, float]]:
    return [
        _safe("safe-aa", "safe-bb"),
        _safe("safe-cc", "safe-dd"),
        _risky("risk-aa", "risk-bb"),
        _risky("risk-cc", "risk-dd"),
        (_profile("mid-aa", "research", read_filesystem=True),
         _profile("mid-bb", "research", network_egress="allowlisted"), 0.45),
        (_profile("low-aa", "support"),
         _profile("low-bb", "support", use_mcp=True), 0.25),
    ]


@pytest.fixture
def all_safe_corpus() -> list[tuple[Profile, Profile, float]]:
    return [_safe(f"s{i}-aa", f"s{i}-bb") for i in range(5)]


def test_band_thresholds():
    assert band_for_composite(0.0) == "safe"
    assert band_for_composite(0.3) == "low"
    assert band_for_composite(0.5) == "medium"
    assert band_for_composite(0.9) == "high"


def test_featurize_is_deterministic_and_order_independent(profile_a, profile_b):
    f1 = featurize(profile_a, profile_b)
    f2 = featurize(profile_b, profile_a)
    assert f1 == f2
    assert len(f1) == len(FEATURE_NAMES)


def test_train_predict_roundtrip_is_deterministic(tiny_corpus):
    m1 = train(tiny_corpus, seed=1234)
    m2 = train(tiny_corpus, seed=1234)
    assert m1.weights == m2.weights
    pa, pb, _ = tiny_corpus[0]
    assert m1.predict(pa, pb).band == m2.predict(pa, pb).band
    assert 0.0 <= m1.predict(pa, pb).uncertainty <= 1.0


def test_safe_pairs_predicted_safe(all_safe_corpus):
    m = train(all_safe_corpus, seed=7)
    pa, pb, _ = all_safe_corpus[0]
    assert m.predict(pa, pb).band == "safe"


def test_artifact_roundtrip(tiny_corpus, tmp_path):
    m = train(tiny_corpus, seed=1)
    path = tmp_path / "v1.json"
    m.save(path, training_set_hash="sha256:" + "0" * 64)
    loaded = TriageModel.load(path)
    pa, pb, _ = tiny_corpus[0]
    assert loaded.predict(pa, pb).band == m.predict(pa, pb).band
    assert loaded.training_set_hash.startswith("sha256:")
