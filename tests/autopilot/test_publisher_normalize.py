"""Tests for normalize_profile_blocks — the schema guard on enriched writes."""

from __future__ import annotations

import json
from pathlib import Path

from smadp.autopilot.publishers.policy import PolicyPublisher, normalize_profile_blocks


def test_required_io_surfaces_filled_others_left_null():
    # io_surfaces is schema-required -> null becomes {}. The other blocks may
    # stay null (the lint tolerates them) so valid profiles aren't churned.
    p = {
        "slug": "x",
        "capabilities": {"network_egress": "none"},
        "io_surfaces": None,
        "permissions_requested": None,
        "sandboxing": None,
        "concurrency_model": None,
    }
    normalize_profile_blocks(p)
    assert p["io_surfaces"] == {}
    for block in ("permissions_requested", "sandboxing", "concurrency_model"):
        assert p[block] is None, block


def test_unknown_keys_are_stripped():
    # An off-schema key under a block (e.g. calls_apis belongs to io_surfaces,
    # not capabilities) is rejected by the schema's extra="forbid".
    p = {
        "slug": "x",
        "capabilities": {"network_egress": "none", "use_mcp": True, "calls_apis": ["x"]},
        "io_surfaces": {"files": ["a"], "bogus": 1},
    }
    normalize_profile_blocks(p)
    assert "calls_apis" not in p["capabilities"]
    assert p["capabilities"]["use_mcp"] is True
    assert "bogus" not in p["io_surfaces"]
    assert p["io_surfaces"]["files"] == ["a"]


def test_boolean_network_egress_maps_to_enum():
    p = {"slug": "x", "capabilities": {"network_egress": False}}
    normalize_profile_blocks(p)
    assert p["capabilities"]["network_egress"] == "none"

    p = {"slug": "x", "capabilities": {"network_egress": True}}
    normalize_profile_blocks(p)
    assert p["capabilities"]["network_egress"] == "broad"


def test_offvocab_network_egress_falls_back_to_none():
    p = {"slug": "x", "capabilities": {"network_egress": "internet"}}
    normalize_profile_blocks(p)
    assert p["capabilities"]["network_egress"] == "none"


def test_valid_blocks_untouched():
    # A valid enum + populated io_surfaces is left exactly as-is (no churn).
    p = {
        "slug": "x",
        "capabilities": {"network_egress": "allowlisted", "use_mcp": True},
        "io_surfaces": {"files": ["local"]},
        "permissions_requested": {},
        "sandboxing": {},
        "concurrency_model": {},
    }
    before = json.loads(json.dumps(p))
    normalize_profile_blocks(p)
    assert p == before


def test_commit_profile_writes_schema_valid(tmp_path: Path):
    pub = PolicyPublisher(catalog_root=tmp_path, auto_publish={})
    out = pub.commit_profile(
        {"slug": "demo", "capabilities": {"network_egress": False}, "io_surfaces": None}
    )
    written = json.loads(out.read_text())
    assert written["capabilities"]["network_egress"] == "none"
    assert written["io_surfaces"] == {}
