from pathlib import Path

from smadp.autopilot.coverage import (
    has_recent_enqueue,
    load_coverage,
    record_enqueued,
)


def test_record_enqueued_persists(tmp_path: Path) -> None:
    p = tmp_path / "coverage.json"
    record_enqueued(p, scenario="s", participants=["a", "b"])
    cov = load_coverage(p)
    assert any(e["scenario"] == "s" and e["participants"] == ["a", "b"] for e in cov["entries"])


def test_has_recent_enqueue_detects_duplicate(tmp_path: Path) -> None:
    p = tmp_path / "coverage.json"
    record_enqueued(p, scenario="s", participants=["a", "b"])
    assert has_recent_enqueue(p, scenario="s", participants=["a", "b"]) is True
    assert has_recent_enqueue(p, scenario="s", participants=["a", "c"]) is False


def test_records_independent_of_participant_order(tmp_path: Path) -> None:
    p = tmp_path / "coverage.json"
    record_enqueued(p, scenario="s", participants=["b", "a"])
    assert has_recent_enqueue(p, scenario="s", participants=["a", "b"]) is True
