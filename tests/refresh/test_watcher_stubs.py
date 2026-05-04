"""Tests for the six fixture-driven stub watchers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.refresh.watchers import iter_watchers
from smadp.refresh.watchers.agent_card import AgentCardWatcher
from smadp.refresh.watchers.dependency_cve import DependencyCveWatcher
from smadp.refresh.watchers.framework_version import FrameworkVersionWatcher
from smadp.refresh.watchers.model_bump import ModelBumpWatcher
from smadp.refresh.watchers.repo_release import RepoReleaseWatcher
from smadp.refresh.watchers.scoring_weights import ScoringWeightsWatcher
from smadp.schemas.refresh import RefreshTrigger


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    return Config()


_WATCHER_PAIRS = [
    (RepoReleaseWatcher, RefreshTrigger.REPO_RELEASE, "repo_release"),
    (DependencyCveWatcher, RefreshTrigger.DEPENDENCY_CVE, "dependency_cve"),
    (ModelBumpWatcher, RefreshTrigger.MODEL_BUMP, "model_bump"),
    (FrameworkVersionWatcher, RefreshTrigger.FRAMEWORK_VERSION, "framework_version"),
    (ScoringWeightsWatcher, RefreshTrigger.SCORING_WEIGHTS, "scoring_weights"),
    (AgentCardWatcher, RefreshTrigger.AGENT_CARD, "agent_card"),
]


@pytest.mark.parametrize("cls,trigger,name", _WATCHER_PAIRS)
def test_stub_watcher_empty_when_no_fixture(
    cls: type, trigger: RefreshTrigger, name: str, cfg: Config
) -> None:
    w = cls()
    assert w.trigger is trigger
    assert w.discover(config=cfg) == []


@pytest.mark.parametrize("cls,trigger,name", _WATCHER_PAIRS)
def test_stub_watcher_reads_fixture(
    cls: type, trigger: RefreshTrigger, name: str, cfg: Config
) -> None:
    fix_dir = cfg.cache_dir / "refresh_fixtures"
    fix_dir.mkdir(parents=True, exist_ok=True)
    payload = [["a__b", {"detail": "x"}], ["c__d", {}]]
    (fix_dir / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")

    found = cls().discover(config=cfg)
    assert [vid for vid, _ in found] == ["a__b", "c__d"]
    assert found[0][1] == {"detail": "x"}


def test_iter_watchers_covers_every_trigger() -> None:
    triggers = {w.trigger for w in iter_watchers()}
    assert triggers == set(RefreshTrigger)
