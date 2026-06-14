from __future__ import annotations

from smadp.analyzer.chains import (
    SEVERITY_BANDS,
    LinkInput,
    bump_band,
    compose_chain,
)


def _link(a, b, *, D="low", B="none", A="none", C="none", E="none",
          conf=0.9, carries=None):
    return LinkInput(
        from_slug=a, to_slug=b,
        severities={"A_prompt_injection": A, "B_data_leakage": B,
                    "C_capability_conflict": C, "D_cascading_error": D,
                    "E_compliance": E},
        confidence=conf, present=True, carries=carries or [],
    )


def test_band_ordering_and_bump():
    assert SEVERITY_BANDS.index("none") < SEVERITY_BANDS.index("critical")
    assert bump_band("low", 1) == "medium"
    assert bump_band("high", 5) == "critical"  # capped
    assert bump_band("none", 0) == "none"


def test_linear_three_node_compounds_D_one_band():
    links = [_link("a", "b", D="low"), _link("b", "c", D="medium")]
    out = compose_chain(topology="linear", links=links, node_count=3)
    assert out.severities["D_cascading_error"] == "high"


def test_loop_amplifies_D_extra_band():
    links = [_link("a", "b", D="low"), _link("b", "a", D="low")]
    out = compose_chain(topology="loop", links=links, node_count=2)
    assert out.severities["D_cascading_error"] == "medium"


def test_B_takes_max_over_links_sharing_data_class():
    links = [
        _link("a", "b", B="low", carries=["pii"]),
        _link("b", "c", B="high", carries=["pii"]),
        _link("c", "d", B="critical", carries=["telemetry"]),
    ]
    out = compose_chain(topology="linear", links=links, node_count=4)
    assert out.severities["B_data_leakage"] == "critical"


def test_confidence_is_min_penalized_per_missing_link():
    present = _link("a", "b", conf=0.8)
    missing = LinkInput(from_slug="b", to_slug="c", severities={
        "A_prompt_injection": "none", "B_data_leakage": "none",
        "C_capability_conflict": "none", "D_cascading_error": "none",
        "E_compliance": "none"}, confidence=0.0, present=False, carries=[])
    out = compose_chain(topology="linear", links=[present, missing], node_count=3)
    assert abs(out.confidence - 0.8 * 0.85) < 1e-9
    assert out.missing_links == 1


def test_composite_uses_existing_weights_deterministically():
    links = [_link("a", "b", B="high", C="medium", D="none")]
    out = compose_chain(topology="linear", links=links, node_count=2)
    assert 0.0 <= out.composite <= 1.0
    assert abs(out.composite - 0.365) < 1e-9
