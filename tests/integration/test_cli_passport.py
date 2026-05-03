"""Integration tests for the smadp passport CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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


def _build_passport(cfg: Config) -> bytes:
    ws = store.create_workspace(name="A", plan=Plan.PUBLIC, config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return render_passport(
        verdict={
            "verdict_id": "vdt_CLI",
            "pair": ["a/x", "b/y"],
            "headline": "CLI test",
            "composite_score": 0.5,
            "framework_mappings": {},
        },
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )


def test_passport_verify_clean_passes(cfg: Config, tmp_path: Path):
    p = tmp_path / "passport.html"
    p.write_bytes(_build_passport(cfg))
    runner = CliRunner()
    result = runner.invoke(cli, ["passport", "verify", str(p)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_passport_verify_tampered_fails(cfg: Config, tmp_path: Path):
    p = tmp_path / "passport.html"
    bad = _build_passport(cfg).replace(b'"verdict_id":"vdt_CLI"', b'"verdict_id":"vdt_HACK"', 1)
    p.write_bytes(bad)
    runner = CliRunner()
    result = runner.invoke(cli, ["passport", "verify", str(p)])
    assert result.exit_code != 0
    assert "INVALID" in result.output or "BREAK" in result.output


def test_passport_verify_missing_file(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["passport", "verify", str(tmp_path / "no.html")])
    assert result.exit_code != 0
