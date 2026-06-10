"""Tests for the ONEXUS-Agents -> SMADP research bridge (sync_onexus)."""

from __future__ import annotations

import json
from pathlib import Path

from smadp.autopilot.agents_sync import KILL_SWITCH, sync_onexus
from smadp.autopilot.work_queue import read_all_items


def _seed(slug: str, score: float, *, github: str | None = "x/" + "repo") -> dict:
    onexus: dict = {"runnable": True}
    if github is not None:
        onexus["source_github"] = github
    return {
        "schema_version": "1.1",
        "slug": slug,
        "name": slug.title(),
        "tagline": "t",
        "vendor": {"type": "individual", "handle": "x"},
        "source_type": "open-source",
        "category": "coding",
        "verification": {
            "status": "unverified",
            "verified_by": None,
            "verified_at": "2026-06-09T00:00:00Z",
            "method": "auto-only",
        },
        "first_seen_at": "2026-06-09T00:00:00Z",
        "last_refreshed_at": "2026-06-09T00:00:00Z",
        "evidence_level": "unverified-profile",
        "composite_score": score,
        "onexus": onexus,
    }


def _repo_with_seeds(tmp_path: Path, seeds: list[dict]) -> Path:
    repo = tmp_path / "repo"
    staging = repo / "catalog" / "profiles" / "_unverified"
    staging.mkdir(parents=True)
    (repo / "state").mkdir()
    for s in seeds:
        (staging / f"{s['slug']}.json").write_text(json.dumps(s))
    return repo


def test_promotes_capped_and_enqueues_highest_score_first(tmp_path: Path) -> None:
    repo = _repo_with_seeds(
        tmp_path,
        [_seed("alpha", 0.9), _seed("beta", 0.8), _seed("gamma", 0.7)],
    )

    summary = sync_onexus(repo_root=repo, max_promote=2)

    assert summary.disabled is False
    assert summary.promoted == 2
    assert summary.queued == 2
    assert summary.staged_remaining == 1

    profiles_dir = repo / "catalog" / "profiles"
    # Highest two scores promoted into profiles/, moved out of _unverified/.
    assert {p.stem for p in profiles_dir.glob("*.json")} == {"alpha", "beta"}
    assert {p.stem for p in (profiles_dir / "_unverified").glob("*.json")} == {"gamma"}

    queued_slugs = {
        item.pair[0] for item in read_all_items(repo / "state" / "docs_only_queue.jsonl")
    }
    assert queued_slugs == {"alpha", "beta"}


def test_kill_switch_blocks_everything(tmp_path: Path) -> None:
    repo = _repo_with_seeds(tmp_path, [_seed("alpha", 0.9)])
    (repo / "state" / KILL_SWITCH).write_text("")

    summary = sync_onexus(repo_root=repo, max_promote=10)

    assert summary.disabled is True
    assert summary.promoted == 0
    assert list((repo / "catalog" / "profiles").glob("*.json")) == []
    assert not (repo / "state" / "docs_only_queue.jsonl").exists()


def test_ineligible_seeds_are_not_promoted(tmp_path: Path) -> None:
    # Missing onexus.source_github -> not queue-eligible.
    repo = _repo_with_seeds(tmp_path, [_seed("nogit", 0.95, github=None)])

    summary = sync_onexus(repo_root=repo, max_promote=10)

    assert summary.promoted == 0
    assert summary.queued == 0
    assert {p.stem for p in (repo / "catalog" / "profiles" / "_unverified").glob("*.json")} == {
        "nogit"
    }


def test_does_not_duplicate_already_researched_slug(tmp_path: Path) -> None:
    repo = _repo_with_seeds(tmp_path, [_seed("alpha", 0.9)])
    # alpha already lives in profiles/ (researched) — must not be promoted again.
    (repo / "catalog" / "profiles" / "alpha.json").write_text(json.dumps(_seed("alpha", 0.9)))

    summary = sync_onexus(repo_root=repo, max_promote=10)

    assert summary.promoted == 0
    # Staging copy is left in place (operator can reconcile); no duplicate created.
    assert (repo / "catalog" / "profiles" / "_unverified" / "alpha.json").exists()
