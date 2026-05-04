"""Tests for smadp.refresh.evaluator — drain_one orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from smadp.config import Config
from smadp.refresh import evaluator, queue, state
from smadp.schemas.refresh import RefreshTrigger
from smadp.schemas.verdict import Verdict


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config()
    (cfg.catalog_dir / "verdicts").mkdir(parents=True, exist_ok=True)
    return cfg


def _real_verdict(sample_verdict: dict[str, Any]) -> Verdict:
    """Coerce the seed sample_verdict dict into a Verdict object."""
    payload = dict(sample_verdict)
    payload["pair"] = tuple(payload["pair"])
    return Verdict.model_validate(payload)


def test_drain_one_returns_none_when_empty(cfg: Config) -> None:
    assert evaluator.drain_one(config=cfg) is None


def test_drain_one_runs_evaluation_and_finalizes(
    cfg: Config, sample_verdict: dict[str, Any]
) -> None:
    verdict = _real_verdict(sample_verdict)
    slug_a, slug_b = verdict.pair
    item = queue.enqueue(
        verdict_id=f"{slug_a}__{slug_b}",
        trigger=RefreshTrigger.MANUAL,
        config=cfg,
    )

    async def fake_generate(*args: Any, **kwargs: Any) -> Verdict:
        return verdict

    with (
        patch(
            "smadp.refresh.evaluator._reload_inputs",
            return_value={"profile_a": object(), "profile_b": object(), "evidence": {}},
        ),
        patch("smadp.refresh.evaluator.generate_verdict", side_effect=fake_generate),
        patch("smadp.refresh.evaluator._save_verdict") as save_mock,
        patch("smadp.refresh.evaluator._emit_transparency") as tx_mock,
        patch("smadp.refresh.evaluator._dispatch_verdict_updated") as dispatch_mock,
    ):
        drained = evaluator.drain_one(config=cfg)

    assert drained is not None and drained.id == item.id
    save_mock.assert_called_once()
    tx_mock.assert_called_once()
    dispatch_mock.assert_called_once()

    s = state.get_state(verdict_id=f"{slug_a}__{slug_b}", config=cfg)
    assert s is not None and s.evaluation_count == 1

    assert queue.list_pending(config=cfg) == []


def _zeroed(sample: dict[str, Any]) -> Verdict:
    payload = dict(sample)
    payload["pair"] = tuple(payload["pair"])
    payload["sub_verdicts"] = {
        k: {**v, "severity": "none"} for k, v in payload["sub_verdicts"].items()
    }
    return Verdict.model_validate(payload)


def test_drain_one_dispatches_framework_coverage_changed_when_delta(
    cfg: Config, sample_verdict: dict[str, Any]
) -> None:
    new = _real_verdict(sample_verdict)
    slug_a, slug_b = new.pair
    old = _zeroed(sample_verdict)
    queue.enqueue(
        verdict_id=f"{slug_a}__{slug_b}",
        trigger=RefreshTrigger.MANUAL,
        config=cfg,
    )

    async def fake_generate(*args: Any, **kwargs: Any) -> Verdict:
        return new

    with (
        patch("smadp.refresh.evaluator._load_verdict_for_pair", return_value=old),
        patch(
            "smadp.refresh.evaluator._reload_inputs",
            return_value={"profile_a": object(), "profile_b": object(), "evidence": {}},
        ),
        patch("smadp.refresh.evaluator._save_verdict"),
        patch("smadp.refresh.evaluator.generate_verdict", side_effect=fake_generate),
        patch("smadp.refresh.evaluator._emit_transparency"),
        patch("smadp.refresh.evaluator._dispatch_verdict_updated"),
        patch(
            "smadp.refresh.evaluator._dispatch_framework_coverage_changed"
        ) as fc_mock,
    ):
        evaluator.drain_one(config=cfg)

    fc_mock.assert_called_once()
    delta = fc_mock.call_args.kwargs["delta"]
    assert set(delta.keys()) == {"added", "removed"}
    assert "LLM01" in delta["added"].get("owasp_llm_top_10", [])


def test_drain_one_skips_framework_coverage_when_no_delta(
    cfg: Config, sample_verdict: dict[str, Any]
) -> None:
    same = _real_verdict(sample_verdict)
    slug_a, slug_b = same.pair
    queue.enqueue(
        verdict_id=f"{slug_a}__{slug_b}",
        trigger=RefreshTrigger.MANUAL,
        config=cfg,
    )

    async def fake_generate(*args: Any, **kwargs: Any) -> Verdict:
        return same

    with (
        patch("smadp.refresh.evaluator._load_verdict_for_pair", return_value=same),
        patch(
            "smadp.refresh.evaluator._reload_inputs",
            return_value={"profile_a": object(), "profile_b": object(), "evidence": {}},
        ),
        patch("smadp.refresh.evaluator._save_verdict"),
        patch("smadp.refresh.evaluator.generate_verdict", side_effect=fake_generate),
        patch("smadp.refresh.evaluator._emit_transparency"),
        patch("smadp.refresh.evaluator._dispatch_verdict_updated"),
        patch(
            "smadp.refresh.evaluator._dispatch_framework_coverage_changed"
        ) as fc_mock,
    ):
        evaluator.drain_one(config=cfg)

    fc_mock.assert_not_called()
