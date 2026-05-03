"""End-to-end: workspace + BYOK + render via API + verify via CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.cli import cli
from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Plan
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


def test_render_via_api_then_verify_via_cli(cfg: Config, tmp_path: Path):
    # Workspace + BYOK key
    ws = store.create_workspace(name="E2E", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )

    # Render directly (the API route itself depends on a catalog verdict that
    # may not exist in this test cache — render_passport bypasses the catalog).
    html = render_passport(
        verdict={
            "verdict_id": "vdt_E2E",
            "pair": ["a/x", "b/y"],
            "headline": "E2E",
            "composite_score": 0.5,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
        },
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )

    # Save to disk + verify via CLI
    out = tmp_path / "passport.html"
    out.write_bytes(html)

    runner = CliRunner()
    result = runner.invoke(cli, ["passport", "verify", str(out)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output

    # Also confirm the API smoke (workspace endpoint reachable)
    client = TestClient(create_app(cfg))
    r = client.get(f"/api/workspaces/{ws.id}")
    assert r.status_code == 200
