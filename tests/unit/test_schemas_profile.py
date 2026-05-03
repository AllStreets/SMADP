"""Tests for ``smadp.schemas.profile`` — Profile Pydantic model."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from smadp.schemas.profile import EVIDENCE_REF_RE, SLUG_RE, Profile


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data: Any = json.load(fh)
    assert isinstance(data, dict)
    return data


def test_loads_every_seed_profile(all_profile_paths: list[Path]) -> None:
    """Every file in catalog/profiles/ must validate cleanly."""
    assert len(all_profile_paths) >= 1, "catalog has no profiles to validate"
    for path in all_profile_paths:
        Profile.model_validate(_load(path))


def test_round_trip(sample_profile: dict[str, Any]) -> None:
    p = Profile.model_validate(sample_profile)
    dumped = p.model_dump(mode="json")
    # Round-trip should be a Profile-equal object (HttpUrl normalization ok).
    p2 = Profile.model_validate(dumped)
    assert p2.slug == p.slug
    assert p2.name == p.name


def test_extra_fields_rejected(sample_profile: dict[str, Any]) -> None:
    payload = deepcopy(sample_profile)
    payload["unexpected_field"] = "nope"
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_extra_field_in_nested_model_rejected(sample_profile: dict[str, Any]) -> None:
    payload = deepcopy(sample_profile)
    payload["capabilities"]["future_capability"] = True
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_invalid_slug_rejected(sample_profile: dict[str, Any]) -> None:
    payload = deepcopy(sample_profile)
    payload["slug"] = "Invalid Slug With Spaces"
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_invalid_evidence_ref_rejected(sample_profile: dict[str, Any]) -> None:
    payload = deepcopy(sample_profile)
    payload["evidence_refs"] = ["sha256:not-a-real-sha"]
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


@pytest.mark.parametrize(
    "good_slug",
    ["a1", "claude-code", "my-agent-007", "x" * 60],
)
def test_slug_regex_accepts(good_slug: str) -> None:
    assert SLUG_RE.match(good_slug) is not None


@pytest.mark.parametrize(
    "bad_slug",
    [
        "A",  # uppercase
        "a",  # too short (must be 2-64 chars)
        "_underscore",
        "-leading-dash",
        "a" * 65,  # too long
        "with space",
        "with.dot",
    ],
)
def test_slug_regex_rejects(bad_slug: str) -> None:
    assert SLUG_RE.match(bad_slug) is None


@pytest.mark.parametrize(
    "good_ref",
    [
        "sha256:" + "0" * 64,
        "sha256:" + "abcdef0123456789" * 4,
    ],
)
def test_evidence_ref_regex_accepts(good_ref: str) -> None:
    assert EVIDENCE_REF_RE.match(good_ref) is not None


@pytest.mark.parametrize(
    "bad_ref",
    [
        "sha256:" + "0" * 63,
        "sha256:" + "0" * 65,
        "sha256:" + "G" * 64,  # non-hex
        "sha512:" + "0" * 64,
        "0" * 64,  # missing prefix
        "",
    ],
)
def test_evidence_ref_regex_rejects(bad_ref: str) -> None:
    assert EVIDENCE_REF_RE.match(bad_ref) is None
