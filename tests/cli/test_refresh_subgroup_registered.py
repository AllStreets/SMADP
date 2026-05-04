"""Sanity test: smadp refresh subgroup is reachable from the root CLI."""

from __future__ import annotations

from click.testing import CliRunner

from smadp.cli import cli


def test_refresh_subgroup_visible_in_help() -> None:
    r = CliRunner().invoke(cli, ["refresh", "--help"])
    assert r.exit_code == 0
    assert "enqueue" in r.output
    assert "drain" in r.output
    assert "ls" in r.output
    assert "poll" in r.output
