"""smadp sandbox pin-images — fetches digest, rewrites approved_images.json."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from smadp.sandbox import pin_images


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
        json.dumps({"aider": "ghcr.io/paul-gauthier/aider@sha256:" + ("0" * 64)}),
        encoding="utf-8",
    )
    adapters_dir = tmp_path / "adapters" / "aider"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "mcp.json").write_text(
        json.dumps({"slug": "aider", "image": "ghcr.io/paul-gauthier/aider:latest", "image_digest_pinned": None}),
        encoding="utf-8",
    )

    digest = "ghcr.io/paul-gauthier/aider@sha256:" + ("a" * 64)
    monkeypatch.setattr(pin_images, "_pull_and_inspect", _fake_inspect_factory({"ghcr.io/paul-gauthier/aider:latest": digest}))

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
    images_path.write_text(json.dumps({"aider": "ghcr.io/paul-gauthier/aider@sha256:" + ("0" * 64)}))
    adapters_dir = tmp_path / "adapters" / "aider"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "mcp.json").write_text(
        json.dumps({"slug": "aider", "image": "ghcr.io/paul-gauthier/aider:latest", "image_digest_pinned": None})
    )
    digest = "ghcr.io/paul-gauthier/aider@sha256:" + ("b" * 64)
    monkeypatch.setattr(pin_images, "_pull_and_inspect", _fake_inspect_factory({"ghcr.io/paul-gauthier/aider:latest": digest}))

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
    with pytest.raises(pin_images.PinImagesError, match="not in approved_images.json"):
        pin_images.pin_images(
            slugs=["does-not-exist"],
            adapters_root=tmp_path / "adapters",
            approved_images_path=images_path,
            dry_run=False,
        )
