"""APPROVED_IMAGES is loaded from JSON and behaves identically to the old constant."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.sandbox import policy


def test_approved_images_is_loaded_from_disk() -> None:
    expected_path = Path(policy.__file__).with_name("approved_images.json")
    assert expected_path.exists(), "approved_images.json must ship with the package"
    raw = json.loads(expected_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    # Every adapter slug we ship must be present.
    for slug in ("aider", "autogen", "continue-dev", "open-interpreter"):
        assert slug in raw, f"missing adapter slug in approved_images.json: {slug}"
    # The in-memory dict must equal the on-disk JSON.
    assert dict(policy.APPROVED_IMAGES) == raw


def test_lookup_image_for_adapter_returns_json_value() -> None:
    raw = json.loads(
        (Path(policy.__file__).with_name("approved_images.json")).read_text(encoding="utf-8")
    )
    assert policy.lookup_image_for_adapter("aider") == raw["aider"]


def test_validate_image_digest_uses_loaded_set() -> None:
    raw = json.loads(
        (Path(policy.__file__).with_name("approved_images.json")).read_text(encoding="utf-8")
    )
    sample = next(iter(raw.values()))
    assert policy.validate_image_digest(sample) is True
    # A well-formed but unknown digest must still be rejected.
    bogus = "ghcr.io/example/unknown@sha256:" + ("0" * 64)
    assert policy.validate_image_digest(bogus) is False


def test_unknown_adapter_raises() -> None:
    with pytest.raises(policy.DisallowedImageError):
        policy.lookup_image_for_adapter("does-not-exist")
