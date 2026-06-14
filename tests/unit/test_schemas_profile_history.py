from __future__ import annotations

import pytest

from smadp.schemas.profile import CapabilityHistoryEntry, Profile

BASE = {
    "slug": "demo-agent",
    "name": "Demo",
    "vendor": {"type": "company", "handle": "acme"},
    "source_type": "open-source",
    "category": "coding",
    "verification": {
        "status": "verified",
        "verified_at": "2026-01-01T00:00:00Z",
        "method": "manual-authoring",
    },
    "first_seen_at": "2026-01-01T00:00:00Z",
    "last_refreshed_at": "2026-01-01T00:00:00Z",
}


def test_capability_history_defaults_empty_and_validates():
    p = Profile.model_validate(BASE)
    assert p.schema_version == "1.2"
    assert p.capability_history == []


def test_capability_history_entry_roundtrip():
    entry = {
        "version": "v2.0.0",
        "observed_at": "2026-06-01T00:00:00Z",
        "capability_hash": "sha256:" + "a" * 64,
        "diff_summary": "added execute_shell",
    }
    p = Profile.model_validate({**BASE, "capability_history": [entry]})
    assert len(p.capability_history) == 1
    assert isinstance(p.capability_history[0], CapabilityHistoryEntry)
    assert p.capability_history[0].capability_hash.startswith("sha256:")


def test_capability_hash_must_be_sha256():
    bad = {
        "version": "v1",
        "observed_at": "2026-06-01T00:00:00Z",
        "capability_hash": "deadbeef",
        "diff_summary": "x",
    }
    with pytest.raises(ValueError):
        Profile.model_validate({**BASE, "capability_history": [bad]})


def test_pre_1_2_profile_still_validates():
    p = Profile.model_validate({**BASE, "schema_version": "1.1"})
    assert p.capability_history == []
