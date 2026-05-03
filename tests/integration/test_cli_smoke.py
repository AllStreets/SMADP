"""Smoke tests for the Click CLI in ``smadp.cli``.

These exercise the read paths (no LLM, no sandbox). Any subcommand that
mutates state runs against a per-test ``tmp_catalog``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from smadp.cli import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0, result.output
    assert "smadp" in result.output.lower()


def test_lint_clean_on_seed_catalog(runner: CliRunner, tmp_catalog: Path) -> None:
    result = runner.invoke(
        cli,
        ["--catalog", str(tmp_catalog), "lint"],
    )
    assert result.exit_code == 0, result.output
    # The renderer prints "all checks passed." when there are no issues.
    assert "all checks passed" in result.output.lower()


def test_validate_clean_on_seed_catalog(runner: CliRunner, tmp_catalog: Path) -> None:
    result = runner.invoke(
        cli,
        ["--catalog", str(tmp_catalog), "validate"],
    )
    assert result.exit_code == 0, result.output


def test_search_returns_claude_code(
    runner: CliRunner,
    tmp_catalog: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_catalog))
    result = runner.invoke(cli, ["search", "claude"])
    assert result.exit_code == 0, result.output
    assert "claude-code" in result.output


def test_help_lists_top_level_subcommands(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for cmd in ("version", "lint", "validate", "search", "verdict", "profile"):
        assert cmd in result.output
