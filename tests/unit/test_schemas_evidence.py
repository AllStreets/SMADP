"""Tests for ``smadp.schemas.evidence`` — Evidence record validation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from smadp.schemas.evidence import Evidence


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data: Any = json.load(fh)
    assert isinstance(data, dict)
    return data


def test_loads_every_seed_evidence(all_evidence_paths: list[Path]) -> None:
    assert len(all_evidence_paths) >= 1
    for path in all_evidence_paths:
        Evidence.model_validate(_load(path))


def test_evidence_ref_property(sample_evidence: dict[str, Any]) -> None:
    e = Evidence.model_validate(sample_evidence)
    assert e.evidence_ref == f"sha256:{e.sha256}"


def test_invalid_sha_rejected(sample_evidence: dict[str, Any]) -> None:
    payload = deepcopy(sample_evidence)
    payload["sha256"] = "G" * 64  # non-hex
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_short_sha_rejected(sample_evidence: dict[str, Any]) -> None:
    payload = deepcopy(sample_evidence)
    payload["sha256"] = "0" * 63
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_extra_fields_rejected(sample_evidence: dict[str, Any]) -> None:
    payload = deepcopy(sample_evidence)
    payload["future_field"] = "x"
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_quote_max_length_enforced() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate(
            {
                "sha256": "0" * 64,
                "source_url": "https://example.com",
                "fetched_at": "2026-05-02T00:00:00Z",
                "fetcher": "test",
                "media_type": "text/plain",
                "quote": "x" * 8001,  # exceeds max_length=8000
            }
        )


def test_empty_quote_rejected() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate(
            {
                "sha256": "0" * 64,
                "source_url": "https://example.com",
                "fetched_at": "2026-05-02T00:00:00Z",
                "fetcher": "test",
                "media_type": "text/plain",
                "quote": "",  # empty rejected by min_length=1
            }
        )
