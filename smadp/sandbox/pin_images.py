"""`smadp sandbox pin-images` — fetch image digests via Docker and pin them.

Reads each `adapters/<slug>/mcp.json` to get the floating tag (e.g.
`ghcr.io/paul-gauthier/aider:latest`), runs `docker pull` + `docker inspect` to
extract the immutable `<repo>@sha256:<hex>` form, then writes the pinned
digest into both:

  - `smadp/sandbox/approved_images.json` (single source of truth for the
    runtime allowlist)
  - `adapters/<slug>/mcp.json` (`image_digest_pinned` field, for human review)

This module is the only place we shell out to `docker` outside the runner.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


class PinImagesError(RuntimeError):
    """Raised on any pin-images failure (missing slug, docker error, etc.)."""


@dataclass
class PinImagesResult:
    changed: dict[str, str] = field(default_factory=dict)
    unchanged: dict[str, str] = field(default_factory=dict)


def pin_images(
    *,
    slugs: list[str] | None,
    adapters_root: Path,
    approved_images_path: Path,
    dry_run: bool,
) -> PinImagesResult:
    """Pin (or preview) image digests for the given adapter slugs."""
    approved = json.loads(approved_images_path.read_text(encoding="utf-8"))
    if not isinstance(approved, dict):
        raise PinImagesError(f"{approved_images_path} must be a JSON object")

    target_slugs = list(slugs) if slugs else _discover_slugs(adapters_root)
    result = PinImagesResult()
    approved_dirty = False

    for slug in target_slugs:
        if slug not in approved:
            raise PinImagesError(
                f"adapter slug {slug!r} is not in approved_images.json — add a stub entry first"
            )
        mcp_path = adapters_root / slug / "mcp.json"
        if not mcp_path.exists():
            raise PinImagesError(f"missing {mcp_path}")
        mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
        floating = mcp.get("image")
        if not isinstance(floating, str) or not floating:
            raise PinImagesError(f"{mcp_path} has no `image` field")

        log.info("sandbox.pin_images.fetching", slug=slug, image=floating)
        digest = _pull_and_inspect(floating)

        old = approved[slug]
        if digest == old and mcp.get("image_digest_pinned") == digest:
            result.unchanged[slug] = digest
            continue
        result.changed[slug] = digest
        if dry_run:
            continue
        approved[slug] = digest
        approved_dirty = True
        mcp["image_digest_pinned"] = digest
        mcp_path.write_text(json.dumps(mcp, indent=2) + "\n", encoding="utf-8")

    if approved_dirty:
        approved_images_path.write_text(
            json.dumps(approved, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return result


def _discover_slugs(adapters_root: Path) -> list[str]:
    if not adapters_root.exists():
        raise PinImagesError(f"adapters root does not exist: {adapters_root}")
    return sorted(p.name for p in adapters_root.iterdir() if (p / "mcp.json").exists())


def _decode_stderr(value: bytes | str | None) -> str:
    """Normalize subprocess stderr to a stripped str regardless of text mode or exception class."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace").strip()
    return value.strip()


def _pull_and_inspect(image_ref: str) -> str:
    """Run `docker pull` then `docker inspect` and extract the first RepoDigest.

    Returns the canonical `<repo>@sha256:<hex>` form. Raises ``PinImagesError``
    on any docker failure (binary missing, pull failure, missing RepoDigests).
    """
    docker = shutil.which("docker") or shutil.which("podman")
    if docker is None:
        raise PinImagesError("neither docker nor podman is on PATH")
    try:
        subprocess.run(
            [docker, "pull", image_ref],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = _decode_stderr(e.stderr)
        raise PinImagesError(
            f"`{docker} pull {image_ref}` failed: {stderr or type(e).__name__}"
        ) from e
    try:
        proc = subprocess.run(
            [docker, "inspect", "--format={{json .RepoDigests}}", image_ref],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = _decode_stderr(e.stderr)
        raise PinImagesError(
            f"`{docker} inspect {image_ref}` failed: {stderr or type(e).__name__}"
        ) from e
    try:
        digests = json.loads(proc.stdout.strip())
    except json.JSONDecodeError as e:
        raise PinImagesError(f"could not parse RepoDigests JSON for {image_ref}: {e}") from e
    if not digests:
        raise PinImagesError(
            f"{image_ref} has no RepoDigests after pull — registry may not "
            "expose content-addressed digests"
        )
    return str(digests[0])


__all__ = ["PinImagesError", "PinImagesResult", "pin_images"]
