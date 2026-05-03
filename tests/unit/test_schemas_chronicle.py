"""Tests for ``smadp.schemas.chronicle`` — daily JSONL audit log records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from smadp.schemas.chronicle import ChronicleEvent


def test_loads_every_seed_chronicle_line(all_chronicle_paths: list[Path]) -> None:
    """Every line in every chronicle file must validate as a ChronicleEvent."""
    assert len(all_chronicle_paths) >= 1, "no chronicle files in catalog"
    total_lines = 0
    for path in all_chronicle_paths:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                obj = json.loads(raw)
                ChronicleEvent.model_validate(obj)
                total_lines += 1
    assert total_lines >= 1, "expected at least one chronicle event"


def test_unknown_event_rejected() -> None:
    with pytest.raises(ValidationError):
        ChronicleEvent.model_validate(
            {
                "ts": "2026-05-02T00:00:00Z",
                "event": "totally.invented.event",
                "by": "tests",
            }
        )


def test_missing_required_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ChronicleEvent.model_validate({"ts": "2026-05-02T00:00:00Z", "by": "tests"})


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ChronicleEvent.model_validate(
            {
                "ts": "2026-05-02T00:00:00Z",
                "event": "profile.created",
                "by": "tests",
                "future_field": 1,
            }
        )


def test_minimal_event_ok() -> None:
    ev = ChronicleEvent.model_validate(
        {
            "ts": "2026-05-02T00:00:00Z",
            "event": "profile.created",
            "by": "tests",
        }
    )
    assert ev.event == "profile.created"
    assert ev.by == "tests"
    assert ev.details == {}
