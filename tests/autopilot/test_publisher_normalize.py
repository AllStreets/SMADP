"""Tests for normalize_profile_blocks — the schema guard on enriched writes."""

from __future__ import annotations

import json
from pathlib import Path

from smadp.autopilot.publishers.policy import PolicyPublisher, normalize_profile_blocks


def test_null_blocks_become_empty_objects():
    p = {
        "slug": "x",
        "capabilities": {"network_egress": "none"},
        "io_surfaces": None,
        "permissions_requested": None,
        "sandboxing": None,
        "concurrency_model": None,
    }
    normalize_profile_blocks(p)
    for block in ("io_surfaces", "permissions_requested", "sandboxing", "concurrency_model"):
        assert p[block] == {}, block


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
