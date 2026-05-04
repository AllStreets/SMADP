"""Profile schema 1.1 — pairings field."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from smadp.schemas import Profile


def _base(**overrides):
    base = {
        "schema_version": "1.1",
        "slug": "demo-agent",
        "name": "Demo Agent",
        "vendor": {"type": "company", "handle": "Demo Inc"},
        "source_type": "open-source",
        "category": "coding",
        "verification": {
            "status": "unverified",
            "verified_at": "2026-05-04T00:00:00Z",
            "method": "auto-only",
        },
        "first_seen_at": "2026-05-04T00:00:00Z",
        "last_refreshed_at": "2026-05-04T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_pairings_default_empty() -> None:
    p = Profile.model_validate(_base())
    assert p.pairings == []


def test_pairings_round_trip() -> None:
    p = Profile.model_validate(_base(pairings=["claude-code", "cursor"]))
    assert p.pairings == ["claude-code", "cursor"]
    dumped = p.model_dump(mode="json", exclude_none=True)
    assert dumped["pairings"] == ["claude-code", "cursor"]


def test_schema_version_1_0_still_valid() -> None:
    p = Profile.model_validate(_base(schema_version="1.0"))
    assert p.schema_version == "1.0"


def test_pairings_max_20() -> None:
    too_many = [f"agent-{i:02d}" for i in range(21)]
    with pytest.raises(ValidationError):
        Profile.model_validate(_base(pairings=too_many))


def test_pairings_invalid_slug_pattern() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate(_base(pairings=["BadSlug"]))
