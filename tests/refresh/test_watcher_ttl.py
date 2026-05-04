"""Tests for the TTL watcher — discovers verdicts whose age exceeds TTL."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from smadp.config import Config
from smadp.refresh.watchers.ttl import TtlWatcher
from smadp.schemas.refresh import RefreshTrigger


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config()
    (cfg.catalog_dir / "verdicts").mkdir(parents=True, exist_ok=True)
    return cfg


def _write_aged_verdict(
    cfg: Config,
    sample: dict[str, Any],
    *,
    slug_a: str,
    slug_b: str,
    generated_at: datetime,
) -> None:
    """Persist a real Verdict-shaped JSON file with the requested timestamp."""
    payload = json.loads(json.dumps(sample))
    a, b = sorted((slug_a, slug_b))
    payload["pair"] = [a, b]
    payload["verdict_id"] = f"v_2026-01-01_{a}__{b}_abcd"
    payload["generated_at"] = generated_at.isoformat()
    path = cfg.catalog_dir / "verdicts" / f"{a}__{b}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_ttl_watcher_discovers_only_expired(
    cfg: Config, sample_verdict: dict[str, Any]
) -> None:
    now = datetime.now(timezone.utc)
    _write_aged_verdict(
        cfg, sample_verdict,
        slug_a="freshone", slug_b="freshtwo",
        generated_at=now - timedelta(days=1),
    )
    _write_aged_verdict(
        cfg, sample_verdict,
        slug_a="oldone", slug_b="oldtwo",
        generated_at=now - timedelta(days=120),
    )

    w = TtlWatcher(ttl_days=90)
    assert w.trigger is RefreshTrigger.TTL
    found = w.discover(config=cfg)
    assert [vid for vid, _ in found] == ["oldone__oldtwo"]
    assert found[0][1]["reason"] == "ttl_expired"
    assert found[0][1]["ttl_days"] == 90


def test_ttl_watcher_returns_empty_when_no_verdicts(cfg: Config) -> None:
    assert TtlWatcher().discover(config=cfg) == []
