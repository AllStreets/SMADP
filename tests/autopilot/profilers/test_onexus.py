"""Tests for OnexusProfiler stub output."""

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


def test_stub_required_keys() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert profile["slug"] == "aider"
    assert profile["name"] == "Aider"
    assert profile["category"] == "coding"
    assert profile["composite_score"] == 0.87
    assert profile["onexus"]["source_github"] == "paul-gauthier/aider"


def test_stub_marked_unverified() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert profile["evidence_level"] == "unverified-profile"


def test_stub_has_no_invented_capabilities() -> None:
    """We no longer infer caps from tags; the enricher does that."""
    profile = OnexusProfiler().normalize(_raw(tags=["shell", "filesystem", "network"]))
    # Capabilities must be None or all-False — the enricher decides the truth.
    caps = profile["capabilities"]
    assert caps is None or all(v is False or v == "none" for v in caps.values())


def test_stub_preserves_docs_urls() -> None:
    profile = OnexusProfiler().normalize(_raw())
    assert "https://aider.chat/" in profile["docs_urls"]
    assert any("github.com/paul-gauthier/aider" in u for u in profile["docs_urls"])


def test_stub_evidence_refs_present() -> None:
    profile = OnexusProfiler().normalize(_raw())
    refs = profile["evidence_refs"]
    assert len(refs) >= 1
    assert all(r.startswith("sha256:") for r in refs)
