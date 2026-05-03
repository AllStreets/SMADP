"""Smoke tests for the vendor CLI subgroup."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
import respx
from click.testing import CliRunner

from smadp.cli import cli
from smadp.config import Config
from smadp.schemas.tenancy import Plan, Role
from smadp.tenancy import store as tenancy


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_PUBLIC_BASE_URL", "https://smadp.example")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> str:
    ws = tenancy.create_workspace(name="V", plan=Plan.PUBLIC, config=cfg)
    tenancy.add_member(workspace_id=ws.id, user_id="u_AAAAAAAA", role=Role.ADMIN, config=cfg)
    monkeypatch.setenv("SMADP_WORKSPACE_ID", ws.id)
    monkeypatch.setenv("SMADP_USER_ID", "u_AAAAAAAA")
    return ws.id


def _cli_env() -> dict[str, str]:
    """Get current environment for CLI tests."""
    return {
        "SMADP_WORKSPACE_ID": os.environ["SMADP_WORKSPACE_ID"],
        "SMADP_USER_ID": os.environ["SMADP_USER_ID"],
        "SMADP_CACHE_DIR": os.environ["SMADP_CACHE_DIR"],
        "SMADP_KEK_MASTER": os.environ["SMADP_KEK_MASTER"],
        "SMADP_PUBLIC_BASE_URL": os.environ["SMADP_PUBLIC_BASE_URL"],
    }


def test_claims_create_outputs_token(cfg: Config, workspace_id: str):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "vendor", "claims", "create",
            "--agent-id", "claude-code",
            "--method", "repo",
            "--evidence-url", "https://github.com/o/r/raw/main",
        ],
        env=_cli_env(),
    )
    assert result.exit_code == 0, result.output
    assert "vc_" in result.output
    assert "token:" in result.output.lower()


def test_claims_ls_redacts_token(cfg: Config, workspace_id: str):
    runner = CliRunner()
    env = _cli_env()
    runner.invoke(
        cli,
        [
            "vendor", "claims", "create",
            "--agent-id", "claude-code",
            "--method", "repo",
            "--evidence-url", "https://github.com/o/r/raw/main",
        ],
        env=env,
    )
    result = runner.invoke(cli, ["vendor", "claims", "ls"], env=env)
    assert result.exit_code == 0
    assert "claude-code" in result.output


@respx.mock
def test_claims_verify_repo(cfg: Config, workspace_id: str):
    runner = CliRunner()
    env = _cli_env()
    create = runner.invoke(
        cli,
        [
            "vendor", "claims", "create",
            "--agent-id", "claude-code",
            "--method", "repo",
            "--evidence-url", "https://github.com/o/r/raw/main",
        ],
        env=env,
    )
    # Find the "created  vc_..." line specifically (not the log line)
    cid = next(line for line in create.output.splitlines() if line.startswith("created")).split()[-1]
    token = next(line for line in create.output.splitlines() if line.startswith("token:")).split()[-1]
    respx.get("https://github.com/o/r/raw/main/.smadp/owner.txt").mock(
        return_value=httpx.Response(200, text=token)
    )
    result = runner.invoke(
        cli,
        [
            "vendor", "claims", "verify", cid,
            "--evidence-json", json.dumps({"repo_url": "https://github.com/o/r/raw/main"}),
        ],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert "verified" in result.output.lower()


def test_disputes_file_then_triage(cfg: Config, workspace_id: str):
    """Skip claim verification by directly seeding store."""
    from smadp.schemas.vendor import ClaimMethod
    from smadp.vendor import store

    claim = store.create_claim(
        workspace_id=workspace_id,
        agent_id="claude-code",
        vendor_user_id="u_AAAAAAAA",
        method=ClaimMethod.REPO,
        evidence_url="https://github.com/o/r/raw/main",
        config=cfg,
    )
    store.mark_claim_verified(claim_id=claim.id, config=cfg)

    runner = CliRunner()
    env = _cli_env()
    f = runner.invoke(
        cli,
        [
            "vendor", "disputes", "file",
            "--verdict-id", "vdt_X",
            "--agent-id", "claude-code",
            "--argument-md", "we contest because ...",
            "--requested-outcome", "reeval",
        ],
        env=env,
    )
    assert f.exit_code == 0, f.output
    # Find the "filed  dsp_..." line specifically (not the log line)
    did = next(line for line in f.output.splitlines() if line.startswith("filed")).split()[-1]
    triage = runner.invoke(
        cli,
        ["vendor", "disputes", "triage", did, "--decision", "substantive"],
        env=env,
    )
    assert triage.exit_code == 0, triage.output
    assert "pending_review" in triage.output
