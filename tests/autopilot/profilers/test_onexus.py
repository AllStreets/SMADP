"""Tests for OnexusProfiler."""

from __future__ import annotations

from smadp.autopilot.profilers.onexus import OnexusProfiler
from smadp.autopilot.sources.onexus import RawOnexusAgent


def _raw(**overrides) -> RawOnexusAgent:
    defaults = dict(
        slug="aider",
        name="Aider",
        category="coding",
        tags=["coding", "shell"],
        author_handle="paul-gauthier",
        source_github="paul-gauthier/aider",
        source_homepage="https://aider.chat/",
        license="Apache-2.0",
        composite_score=0.87,
        runnable=False,
    )
    defaults.update(overrides)
    return RawOnexusAgent(**defaults)


def test_normalize_produces_required_keys() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert profile["slug"] == "aider"
    assert profile["name"] == "Aider"
    assert profile["category"] == "coding"
    assert profile["evidence_level"] == "docs-only"
    assert profile["composite_score"] == 0.87
    assert profile["onexus"]["source_github"] == "paul-gauthier/aider"


def test_normalize_infers_capabilities_from_tags() -> None:
    profile = OnexusProfiler().normalize(_raw(tags=["shell", "filesystem", "network"]))
    caps = profile["capabilities"]
    assert caps["execute_shell"] is True
    assert caps["read_filesystem"] is True
    assert caps["write_filesystem"] is True
    assert caps["network_egress"] in ("broad", "narrow", "none")


def test_normalize_capabilities_default_to_unknown_when_no_signal() -> None:
    profile = OnexusProfiler().normalize(_raw(tags=["mystery-tag"]))
    caps = profile["capabilities"]
    # absent signals -> conservative defaults (False, "none")
    assert caps["execute_shell"] is False
    assert caps["network_egress"] == "none"


def test_normalize_includes_docs_evidence_ref() -> None:
    profile = OnexusProfiler().normalize(_raw())
    refs = profile["evidence_refs"]
    assert len(refs) >= 1
    # evidence refs are sha256-prefixed strings
    assert all(r.startswith("sha256:") for r in refs)


def test_normalize_preserves_docs_urls() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert "https://aider.chat/" in profile["docs_urls"]
    assert any("github.com/paul-gauthier/aider" in u for u in profile["docs_urls"])
