"""Tests for PolicyPublisher."""

from __future__ import annotations

import json
from pathlib import Path

from smadp.autopilot.publishers.policy import PolicyPublisher


def _verdict(evidence_level: str) -> dict:
    return {
        "schema_version": "1.0",
        "verdict_id": f"v_test_{evidence_level}",
        "pair": ["aider", "cursor"],
        "evidence_level": evidence_level,
        "composite_score": 0.3,
        "model": {"name": "gpt-5.4-mini", "id": "gpt-5.4-mini", "rubric_version": "1.0"},
        "headline": "h",
        "sub_verdicts": {},
        "framework_mappings": {},
        "confidence": 0.7,
        "generated_at": "2026-06-06T00:00:00Z",
    }


def test_docs_only_writes_to_verdicts(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    path = pub.commit(_verdict("docs-only"))
    assert path.parent.name == "verdicts"
    assert json.loads(path.read_text())["evidence_level"] == "docs-only"


def test_sandbox_writes_to_pending_when_auto_disabled(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    path = pub.commit(_verdict("sandbox-run"))
    assert path.parent.name == "pending"


def test_commit_is_atomic_and_overwrites(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": True},
    )
    v = _verdict("docs-only")
    path_first = pub.commit(v)
    v2 = {**v, "composite_score": 0.99}
    path_second = pub.commit(v2)
    assert path_first == path_second
    assert json.loads(path_second.read_text())["composite_score"] == 0.99


def test_commit_creates_parent_dirs(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "fresh-catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    path = pub.commit(_verdict("docs-only"))
    assert path.exists()
    assert path.parent.exists()


def test_commit_profile_writes_to_profiles(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    profile = {
        "slug": "aider",
        "name": "Aider",
        "evidence_level": "docs-only",
        "capabilities": {"execute_shell": True},
    }
    path = pub.commit_profile(profile)
    assert path.parent.name == "profiles"
    assert path.name == "aider.json"
    written = json.loads(path.read_text())
    assert written["capabilities"]["execute_shell"] is True


def test_commit_profile_overwrites(tmp_path: Path) -> None:
    pub = PolicyPublisher(
        catalog_root=tmp_path / "catalog",
        auto_publish={"docs-only": True, "profile-verified": True, "sandbox-run": False},
    )
    pub.commit_profile({"slug": "aider", "name": "v1"})
    pub.commit_profile({"slug": "aider", "name": "v2"})
    out = json.loads((tmp_path / "catalog" / "profiles" / "aider.json").read_text())
    assert out["name"] == "v2"
