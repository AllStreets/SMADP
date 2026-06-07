"""Tests for verify_adapter_build."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from smadp.autopilot.scaffolders.docker_verify import (
    verify_adapter_build,
)


def _make_adapter_dir(tmp_path: Path) -> Path:
    d = tmp_path / "myagent"
    d.mkdir()
    (d / "Dockerfile").write_text("FROM busybox\n")
    (d / "mcp.json").write_text("{}")
    return d


def test_returns_skipped_when_docker_missing(tmp_path: Path) -> None:
    adapter = _make_adapter_dir(tmp_path)
    with patch("smadp.autopilot.scaffolders.docker_verify.docker_available", return_value=False):
        result = verify_adapter_build(adapter, image_tag="smadp/agent/myagent:latest")
    assert result.skipped
    assert result.reason == "docker_unavailable"


def test_returns_success_when_docker_build_returns_zero(tmp_path: Path) -> None:
    adapter = _make_adapter_dir(tmp_path)
    fake = type("CP", (), {"returncode": 0, "stdout": b"built", "stderr": b""})()
    with (
        patch("smadp.autopilot.scaffolders.docker_verify.docker_available", return_value=True),
        patch("smadp.autopilot.scaffolders.docker_verify.subprocess.run", return_value=fake),
    ):
        result = verify_adapter_build(adapter, image_tag="smadp/agent/myagent:latest")
    assert result.success
    assert not result.skipped


def test_returns_failure_when_docker_build_returns_nonzero(tmp_path: Path) -> None:
    adapter = _make_adapter_dir(tmp_path)
    fake = type("CP", (), {"returncode": 1, "stdout": b"", "stderr": b"build failed"})()
    with (
        patch("smadp.autopilot.scaffolders.docker_verify.docker_available", return_value=True),
        patch("smadp.autopilot.scaffolders.docker_verify.subprocess.run", return_value=fake),
    ):
        result = verify_adapter_build(adapter, image_tag="smadp/agent/myagent:latest")
    assert not result.success
    assert "build failed" in result.build_log_tail
