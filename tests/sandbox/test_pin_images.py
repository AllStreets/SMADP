"""smadp sandbox pin-images — fetches digest, rewrites approved_images.json."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from smadp.sandbox import pin_images

_AIDER_IMAGE = "ghcr.io/paul-gauthier/aider:latest"
_AIDER_BASE = "ghcr.io/paul-gauthier/aider@sha256:"


def _fake_inspect_factory(mapping: dict[str, str]):
    """Return a callable that mimics `docker inspect` for the given image refs."""

    def fake(image: str) -> str:
        if image not in mapping:
            raise pin_images.PinImagesError(f"no fake digest for {image}")
        return mapping[image]

    return fake


def test_pin_one_adapter_writes_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Stage a copy of approved_images.json + an adapters/aider/mcp.json under tmp_path.
    images_path = tmp_path / "approved_images.json"
    images_path.write_text(
        json.dumps({"aider": _AIDER_BASE + ("0" * 64)}),
        encoding="utf-8",
    )
    adapters_dir = tmp_path / "adapters" / "aider"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "mcp.json").write_text(
        json.dumps(
            {"slug": "aider", "image": _AIDER_IMAGE, "image_digest_pinned": None}
        ),
        encoding="utf-8",
    )

    digest = _AIDER_BASE + ("a" * 64)
    monkeypatch.setattr(
        pin_images, "_pull_and_inspect", _fake_inspect_factory({_AIDER_IMAGE: digest})
    )

    result = pin_images.pin_images(
        slugs=["aider"],
        adapters_root=tmp_path / "adapters",
        approved_images_path=images_path,
        dry_run=False,
    )

    # approved_images.json updated.
    assert json.loads(images_path.read_text(encoding="utf-8"))["aider"] == digest
    # mcp.json updated.
    mcp = json.loads((adapters_dir / "mcp.json").read_text(encoding="utf-8"))
    assert mcp["image_digest_pinned"] == digest
    # Result reports what changed.
    assert result.changed == {"aider": digest}


def test_dry_run_does_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    images_path = tmp_path / "approved_images.json"
    images_path.write_text(json.dumps({"aider": _AIDER_BASE + ("0" * 64)}))
    adapters_dir = tmp_path / "adapters" / "aider"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "mcp.json").write_text(
        json.dumps(
            {"slug": "aider", "image": _AIDER_IMAGE, "image_digest_pinned": None}
        )
    )
    digest = _AIDER_BASE + ("b" * 64)
    monkeypatch.setattr(
        pin_images, "_pull_and_inspect", _fake_inspect_factory({_AIDER_IMAGE: digest})
    )

    result = pin_images.pin_images(
        slugs=["aider"],
        adapters_root=tmp_path / "adapters",
        approved_images_path=images_path,
        dry_run=True,
    )
    # Files unchanged.
    assert json.loads(images_path.read_text())["aider"].endswith("0" * 64)
    assert json.loads((adapters_dir / "mcp.json").read_text())["image_digest_pinned"] is None
    # Result still reports the would-be change.
    assert result.changed == {"aider": digest}


def test_unknown_slug_raises(tmp_path: Path) -> None:
    images_path = tmp_path / "approved_images.json"
    images_path.write_text("{}")
    with pytest.raises(pin_images.PinImagesError, match=r"not in approved_images\.json"):
        pin_images.pin_images(
            slugs=["does-not-exist"],
            adapters_root=tmp_path / "adapters",
            approved_images_path=images_path,
            dry_run=False,
        )


def test_unchanged_path_does_not_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When digest already matches, no file is rewritten and result reports unchanged."""
    digest = _AIDER_BASE + ("c" * 64)
    images_path = tmp_path / "approved_images.json"
    images_path.write_text(json.dumps({"aider": digest}), encoding="utf-8")
    images_mtime = images_path.stat().st_mtime_ns

    adapters_dir = tmp_path / "adapters" / "aider"
    adapters_dir.mkdir(parents=True)
    mcp_path = adapters_dir / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            {"slug": "aider", "image": _AIDER_IMAGE, "image_digest_pinned": digest}
        ),
        encoding="utf-8",
    )
    mcp_mtime = mcp_path.stat().st_mtime_ns

    monkeypatch.setattr(
        pin_images, "_pull_and_inspect", _fake_inspect_factory({_AIDER_IMAGE: digest})
    )

    result = pin_images.pin_images(
        slugs=["aider"],
        adapters_root=tmp_path / "adapters",
        approved_images_path=images_path,
        dry_run=False,
    )

    assert result.unchanged == {"aider": digest}
    assert result.changed == {}
    # Files were not rewritten (mtime unchanged).
    assert images_path.stat().st_mtime_ns == images_mtime
    assert mcp_path.stat().st_mtime_ns == mcp_mtime


def test_pull_and_inspect_handles_unparseable_repodigests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bad JSON from `docker inspect` raises PinImagesError, not JSONDecodeError."""

    def fake_which(name: str):
        return "/usr/bin/" + name if name == "docker" else None

    fake_pull = mock.Mock(returncode=0, stdout="", stderr="")
    fake_inspect = mock.Mock(returncode=0, stdout="not json", stderr="")

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if "pull" in cmd:
            return fake_pull
        return fake_inspect

    monkeypatch.setattr(pin_images.shutil, "which", fake_which)
    monkeypatch.setattr(pin_images.subprocess, "run", fake_run)

    with pytest.raises(pin_images.PinImagesError, match=r"could not parse RepoDigests JSON"):
        pin_images._pull_and_inspect("ghcr.io/example/aider:latest")


def test_pull_timeout_raises_friendly_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A TimeoutExpired during `docker pull` becomes PinImagesError, not a raw traceback."""
    import subprocess as _subprocess

    def fake_which(name: str) -> str | None:
        return "/usr/bin/docker" if name == "docker" else None

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if "pull" in cmd:
            # text=True semantics: stderr is a str, not bytes
            raise _subprocess.TimeoutExpired(cmd=cmd, timeout=600, output="", stderr="pull stalled")
        raise AssertionError("inspect should not be called after pull timeout")

    monkeypatch.setattr(pin_images.shutil, "which", fake_which)
    monkeypatch.setattr(pin_images.subprocess, "run", fake_run)

    with pytest.raises(pin_images.PinImagesError, match=r"failed: pull stalled"):
        pin_images._pull_and_inspect("ghcr.io/example/aider:latest")
