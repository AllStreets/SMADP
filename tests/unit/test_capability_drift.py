from __future__ import annotations

from smadp.analyzer.capability_drift import (
    EGRESS_ORDER,
    capability_hash,
    diff_capabilities,
)
from smadp.schemas.profile import Profile

BASE = {
    "slug": "aa", "name": "A",
    "vendor": {"type": "company", "handle": "x"},
    "source_type": "open-source", "category": "coding",
    "verification": {"status": "verified", "verified_at": "2026-01-01T00:00:00Z",
                     "method": "manual-authoring"},
    "first_seen_at": "2026-01-01T00:00:00Z", "last_refreshed_at": "2026-01-01T00:00:00Z",
}


def _profile(**caps):
    return Profile.model_validate({**BASE, "capabilities": caps})


def test_egress_order_is_monotonic():
    assert EGRESS_ORDER["none"] < EGRESS_ORDER["allowlisted"]
    assert EGRESS_ORDER["allowlisted"] < EGRESS_ORDER["vendor-only"]
    assert EGRESS_ORDER["vendor-only"] < EGRESS_ORDER["broad"]


def test_hash_is_stable_and_order_independent():
    p1 = _profile(execute_shell=True, read_filesystem=True)
    p2 = _profile(read_filesystem=True, execute_shell=True)
    assert capability_hash(p1) == capability_hash(p2)
    assert capability_hash(p1).startswith("sha256:")


def test_new_execute_shell_is_expansion():
    old = _profile(execute_shell=False)
    new = _profile(execute_shell=True)
    d = diff_capabilities(old, new)
    assert d.has_expansion
    assert any("execute_shell" in c.field for c in d.expansions)
    assert d.expansions[0].direction == "expansion"


def test_broader_egress_is_expansion():
    old = _profile(network_egress="allowlisted")
    new = _profile(network_egress="broad")
    d = diff_capabilities(old, new)
    assert d.has_expansion
    assert any("network_egress" in c.field for c in d.expansions)


def test_narrower_egress_is_contraction_not_expansion():
    old = _profile(network_egress="broad")
    new = _profile(network_egress="allowlisted")
    d = diff_capabilities(old, new)
    assert not d.has_expansion
    assert any(c.direction == "contraction" for c in d.contractions)


def test_new_oauth_scope_is_expansion():
    old = Profile.model_validate({**BASE})
    new = Profile.model_validate(
        {**BASE, "permissions_requested": {"oauth_scopes": ["repo:write"]}}
    )
    d = diff_capabilities(old, new)
    assert d.has_expansion
    assert any("oauth_scopes" in c.field for c in d.expansions)


def test_identical_profiles_no_drift():
    p = _profile(execute_shell=True)
    d = diff_capabilities(p, p)
    assert not d.has_expansion
    assert d.summary == "no capability change"
