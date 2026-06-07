"""Docker build verification for scaffolded adapters."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DockerVerifyResult:
    success: bool
    skipped: bool = False
    reason: str = ""
    image_tag: str = ""
    build_log_tail: str = ""


def docker_available() -> bool:
    return shutil.which("docker") is not None


def verify_adapter_build(
    adapter_dir: Path,
    *,
    image_tag: str,
    timeout_s: int = 600,
) -> DockerVerifyResult:
    """Run `docker build` inside adapter_dir and report the outcome.

    On systems without docker installed, returns skipped=True so the smoke
    can fail-soft on dev machines without Docker.
    """
    if not docker_available():
        return DockerVerifyResult(
            success=False, skipped=True, reason="docker_unavailable", image_tag=image_tag
        )

    try:
        completed = subprocess.run(
            ["docker", "build", "-t", image_tag, str(adapter_dir)],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DockerVerifyResult(
            success=False,
            reason="build_timeout",
            image_tag=image_tag,
            build_log_tail=f"timed out after {timeout_s}s",
        )

    tail = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="replace")
    tail = tail[-4000:]
    if completed.returncode != 0:
        return DockerVerifyResult(
            success=False,
            reason="build_failed",
            image_tag=image_tag,
            build_log_tail=tail,
        )
    return DockerVerifyResult(success=True, image_tag=image_tag, build_log_tail=tail)
