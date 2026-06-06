"""Tests for OnexusSource."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.autopilot.sources.onexus import OnexusSource, RawOnexusAgent

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "onexus"


def test_fetch_yields_all_records_from_fixture() -> None:
    source = OnexusSource(root=FIXTURE_ROOT)
    records = list(source.fetch())
    slugs = sorted(r.slug for r in records)
    assert slugs == ["fixture-agent-a", "fixture-agent-b"]


def test_fetch_yields_typed_records() -> None:
    source = OnexusSource(root=FIXTURE_ROOT)
    by_slug = {r.slug: r for r in source.fetch()}
    a = by_slug["fixture-agent-a"]
    assert isinstance(a, RawOnexusAgent)
    assert a.category == "coding"
    assert a.tags == ["ai-agents", "github", "cli"]
    assert a.composite_score == 0.91
    assert a.source_github == "octocat/fixture-a"


def test_fetch_skips_invalid_json(tmp_path: Path) -> None:
    cat = tmp_path / "broken"
    cat.mkdir()
    (cat / "bad.json").write_text("this is not json")
    (cat / "good.json").write_text(
        '{"slug":"good","name":"G","category":"broken","tags":[],'
        '"author":{"type":"user","handle":"x","url":""},'
        '"source":{"primary":"github","github":"x/g","homepage":null},'
        '"license":"MIT","metrics":{"stars":0,"downloads_30d":null,"last_commit_at":""},'
        '"runnable":false,"adapter_ref":null,"composite_score":0.1,"rank_in_category":1}'
    )
    source = OnexusSource(root=tmp_path)
    slugs = [r.slug for r in source.fetch()]
    assert slugs == ["good"]


def test_fetch_returns_empty_when_root_missing(tmp_path: Path) -> None:
    source = OnexusSource(root=tmp_path / "nope")
    assert list(source.fetch()) == []
