"""Tests for bootstrap_onexus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.autopilot.bootstrap import BootstrapSummary, bootstrap_onexus


@pytest.fixture
def fixture_catalog(tmp_path: Path) -> Path:
    root = tmp_path / "onexus-fixture" / "coding"
    root.mkdir(parents=True)
    for slug, score in [("alpha", 0.91), ("beta", 0.82), ("gamma", 0.73)]:
        (root / f"{slug}.json").write_text(
            json.dumps(
                {
                    "slug": slug,
                    "name": slug.title(),
                    "category": "coding",
                    "tags": ["coding"],
                    "author": {"type": "user", "handle": "x", "url": ""},
                    "source": {"primary": "github", "github": f"x/{slug}", "homepage": None},
                    "license": "MIT",
                    "metrics": {"stars": 1, "downloads_30d": None, "last_commit_at": ""},
                    "runnable": False,
                    "adapter_ref": None,
                    "composite_score": score,
                    "rank_in_category": 1,
                }
            )
        )
    return tmp_path / "onexus-fixture"


def test_bootstrap_writes_stubs_and_queues_enrichment(
    fixture_catalog: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    summary = bootstrap_onexus(
        repo_root=repo,
        onexus_root=fixture_catalog,
        top_n=10,
        pair_cap=10,
    )
    assert isinstance(summary, BootstrapSummary)
    assert summary.profiles_written == 3
    assert summary.pairs_queued == 3  # 3 enrichment items, not 3C2

    profiles_dir = repo / "catalog" / "profiles"
    assert {p.stem for p in profiles_dir.glob("*.json")} == {"alpha", "beta", "gamma"}
    for p in profiles_dir.glob("*.json"):
        d = json.loads(p.read_text())
        assert d["evidence_level"] == "unverified-profile"

    queue_path = repo / "state" / "docs_only_queue.jsonl"
    assert queue_path.exists()
    lines = queue_path.read_text("utf-8").strip().splitlines()
    assert len(lines) == 3
    items = [json.loads(line) for line in lines]
    assert all(i["requested_judge"] == "profile_enrich" for i in items)
    assert all(i["pair"][0] == i["pair"][1] for i in items)


def test_bootstrap_skips_manual_profiles(fixture_catalog: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "catalog" / "profiles").mkdir(parents=True)
    (repo / "catalog" / "profiles" / "alpha.json").write_text(
        json.dumps({"slug": "alpha", "manual": True, "name": "Hand-written"})
    )
    summary = bootstrap_onexus(
        repo_root=repo,
        onexus_root=fixture_catalog,
        top_n=10,
        pair_cap=10,
    )
    preserved = json.loads((repo / "catalog" / "profiles" / "alpha.json").read_text())
    assert preserved == {"slug": "alpha", "manual": True, "name": "Hand-written"}
    assert summary.profiles_skipped == 1
    assert summary.profiles_written == 2
    # Enrichment items queued only for the 2 written (alpha stays hand-curated; if it
    # is already enriched the EnrichmentPlanner will skip it, since its evidence_level
    # is not "unverified-profile").
    assert summary.pairs_queued == 2


def test_bootstrap_is_idempotent(fixture_catalog: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    first = bootstrap_onexus(
        repo_root=repo,
        onexus_root=fixture_catalog,
        top_n=10,
        pair_cap=10,
    )
    second = bootstrap_onexus(
        repo_root=repo,
        onexus_root=fixture_catalog,
        top_n=10,
        pair_cap=10,
    )
    queue_lines = (repo / "state" / "docs_only_queue.jsonl").read_text("utf-8").strip().splitlines()
    assert len(queue_lines) == first.pairs_queued == second.pairs_queued


def test_bootstrap_skips_already_enriched_profiles(fixture_catalog: Path, tmp_path: Path) -> None:
    """A docs-only profile on disk must NOT be overwritten with a stub."""
    repo = tmp_path / "repo"
    (repo / "catalog" / "profiles").mkdir(parents=True)
    enriched = {
        "slug": "alpha",
        "evidence_level": "docs-only",
        "capabilities": {"execute_shell": True},
        "name": "Hand-enriched Alpha",
    }
    (repo / "catalog" / "profiles" / "alpha.json").write_text(json.dumps(enriched))
    summary = bootstrap_onexus(
        repo_root=repo,
        onexus_root=fixture_catalog,
        top_n=10,
        pair_cap=10,
    )
    preserved = json.loads((repo / "catalog" / "profiles" / "alpha.json").read_text())
    assert preserved == enriched  # untouched
    assert summary.profiles_skipped == 1
    # alpha also must not appear in the enrichment queue.
    queue_lines = (repo / "state" / "docs_only_queue.jsonl").read_text("utf-8").strip().splitlines()
    items = [json.loads(line) for line in queue_lines]
    assert "alpha" not in {i["pair"][0] for i in items}
