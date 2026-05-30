from pathlib import Path
from smadp.autopilot.priority import load_priority


def test_empty_when_missing(tmp_path: Path) -> None:
    assert load_priority(tmp_path / "missing.yaml") == []


def test_parses_entries(tmp_path: Path) -> None:
    p = tmp_path / "priority.yaml"
    p.write_text(
        "priority:\n"
        "  - { scenario: s1, agents: [a, b] }\n"
        "  - { scenario: s2, agents: [c, d, e] }\n"
    )
    entries = load_priority(p)
    assert entries == [
        {"scenario": "s1", "agents": ["a", "b"]},
        {"scenario": "s2", "agents": ["c", "d", "e"]},
    ]
