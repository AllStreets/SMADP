"""Integration: POST /api/refresh → drain_one → verdict re-saved + webhook.

Exercises the manual-refresh path end-to-end using mocks for the analyzer
LLM call and the webhook signing key. Verifies that the verdict JSON on
disk reflects the regenerated payload after the queue is drained.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.refresh import api as refresh_api
from smadp.refresh import evaluator, queue
from smadp.schemas.tenancy import Plan, Role
from smadp.schemas.verdict import Verdict
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config()
    cfg.catalog_dir.mkdir(parents=True, exist_ok=True)
    (cfg.catalog_dir / "verdicts").mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="R", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(
        workspace_id=ws.id, user_id="u_ADMIN001", role=Role.ADMIN, config=cfg
    )
    return ws.id


@pytest.fixture
def client(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("smadp.refresh.api.load_config", lambda: cfg)
    app = create_app(cfg)
    app.include_router(refresh_api.router, prefix="/api")
    return TestClient(app)


def _seed_verdict(cfg: Config, sample_verdict: dict[str, Any]) -> Verdict:
    payload = dict(sample_verdict)
    payload["pair"] = tuple(payload["pair"])
    verdict = Verdict.model_validate(payload)
    CatalogRepo(config=cfg).save_verdict(verdict)
    return verdict


def test_post_refresh_then_drain_updates_verdict_file_and_dispatches(
    client: TestClient,
    cfg: Config,
    workspace_id: str,
    sample_verdict: dict[str, Any],
) -> None:
    seed = _seed_verdict(cfg, sample_verdict)
    slug_a, slug_b = seed.pair
    verdict_id = f"{slug_a}__{slug_b}"

    resp = client.post(
        "/api/refresh",
        json={"verdict_id": verdict_id, "reason": "smoke"},
        headers={
            "X-SMADP-Workspace": workspace_id,
            "X-SMADP-User": "u_ADMIN001",
        },
    )
    assert resp.status_code == 201, resp.text
    pending = queue.list_pending(config=cfg)
    assert [p.verdict_id for p in pending] == [verdict_id]

    refreshed_payload = dict(sample_verdict)
    refreshed_payload["pair"] = tuple(refreshed_payload["pair"])
    refreshed_payload["headline"] = "post-refresh headline"
    refreshed_payload["composite_score"] = 0.42
    refreshed = Verdict.model_validate(refreshed_payload)

    async def fake_generate(*_args: Any, **_kw: Any) -> Verdict:
        return refreshed

    with (
        patch(
            "smadp.refresh.evaluator._reload_inputs",
            return_value={"profile_a": object(), "profile_b": object(), "evidence": {}},
        ),
        patch("smadp.refresh.evaluator.generate_verdict", side_effect=fake_generate),
        patch("smadp.refresh.evaluator._emit_transparency"),
        patch("smadp.refresh.evaluator._dispatch_verdict_updated") as dispatched,
    ):
        item = evaluator.drain_one(config=cfg)

    assert item is not None and item.verdict_id == verdict_id
    dispatched.assert_called_once()

    on_disk = json.loads(
        (cfg.catalog_dir / "verdicts" / f"{verdict_id}.json").read_text("utf-8")
    )
    assert on_disk["headline"] == "post-refresh headline"
    assert on_disk["composite_score"] == 0.42
    assert queue.list_pending(config=cfg) == []
