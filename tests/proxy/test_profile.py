"""Behavior-profile synthesis derives observed runtime surfaces, deterministically."""
from __future__ import annotations

from smadp.proxy.profile import synthesize_behavior_profile
from smadp.schemas.profile import Profile

_RECORDING = [
    {
        "direction": "c2s",
        "message": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "/etc/hosts"}},
        },
    },
    {
        "direction": "c2s",
        "message": {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "http_get", "arguments": {"url": "https://api.acme.com/v1"}},
        },
    },
]


def test_synthesis_lands_behavior_observed_with_runtime_surfaces() -> None:
    out = synthesize_behavior_profile(
        slug="acme-agent",
        name="Acme Agent",
        messages=_RECORDING,
        evidence_ref="sha256:" + "a" * 64,
    )
    assert out["evidence_level"] == "behavior-observed"
    behavior = out["onexus"]["behavior"]
    assert "read_file" in behavior["observed_tools"]
    assert "http_get" in behavior["observed_tools"]
    assert "api.acme.com" in behavior["network_hosts"]
    assert "/etc/hosts" in behavior["file_paths"]
    assert out["evidence_refs"] == ["sha256:" + "a" * 64]


def test_synthesis_is_deterministic() -> None:
    a = synthesize_behavior_profile(
        slug="acme-agent", name="Acme Agent", messages=_RECORDING, evidence_ref="sha256:" + "b" * 64
    )
    b = synthesize_behavior_profile(
        slug="acme-agent", name="Acme Agent", messages=_RECORDING, evidence_ref="sha256:" + "b" * 64
    )
    a.pop("first_seen_at", None)
    a.pop("last_refreshed_at", None)
    b.pop("first_seen_at", None)
    b.pop("last_refreshed_at", None)
    assert a == b


def test_synthesized_stub_validates_against_profile_schema() -> None:
    out = synthesize_behavior_profile(
        slug="acme-agent",
        name="Acme Agent",
        messages=_RECORDING,
        evidence_ref="sha256:" + "c" * 64,
    )
    model = Profile.model_validate(out)
    assert model.evidence_level == "behavior-observed"
