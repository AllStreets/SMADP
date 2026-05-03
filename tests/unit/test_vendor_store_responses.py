"""Unit tests for vendor.store response CRUD."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.schemas.tenancy import Plan
from smadp.tenancy import store as tenancy
from smadp.vendor import store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    return ws.id


def test_post_response_returns_id(cfg: Config, workspace_id: str):
    r = store.post_response(
        workspace_id=workspace_id,
        verdict_id="vdt_X",
        vendor_user_id="user_a",
        body_md="we mitigated this",
        config=cfg,
    )
    assert r.id.startswith("vr_")
    assert r.body_md == "we mitigated this"


def test_list_responses_for_verdict(cfg: Config, workspace_id: str):
    a = store.post_response(
        workspace_id=workspace_id,
        verdict_id="vdt_X",
        vendor_user_id="user_a",
        body_md="first",
        config=cfg,
    )
    b = store.post_response(
        workspace_id=workspace_id,
        verdict_id="vdt_X",
        vendor_user_id="user_a",
        body_md="second",
        config=cfg,
    )
    store.post_response(
        workspace_id=workspace_id,
        verdict_id="vdt_OTHER",
        vendor_user_id="user_a",
        body_md="other",
        config=cfg,
    )
    ids = {r.id for r in store.list_responses(workspace_id=workspace_id, verdict_id="vdt_X", config=cfg)}
    assert ids == {a.id, b.id}
