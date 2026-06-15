"""Daily report capability-creep section."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from smadp.autopilot.daily_report import render_report


def _write_chronicle(repo_root: Path, when: date, events: list[dict]) -> None:
    cdir = repo_root / "catalog" / "_chronicle"
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / f"{when.isoformat()}.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def test_capability_creep_section_present(tmp_path: Path) -> None:
    when = date(2026, 6, 11)
    _write_chronicle(
        tmp_path,
        when,
        [
            {
                "ts": "2026-06-11T00:00:00Z",
                "event": "capability_drift",
                "by": "autopilot",
                "slug": "demo-agent",
                "details": {"expansions": ["execute_shell"], "summary": "expanded: execute_shell"},
            }
        ],
    )
    out = render_report(repo_root=tmp_path, today=when)
    assert "## Capability creep" in out
    assert "demo-agent" in out
    assert "execute_shell" in out


def test_capability_creep_section_omitted_when_no_drift(tmp_path: Path) -> None:
    when = date(2026, 6, 11)
    _write_chronicle(
        tmp_path,
        when,
        [{"ts": "2026-06-11T00:00:00Z", "event": "profile.created", "by": "x"}],
    )
    out = render_report(repo_root=tmp_path, today=when)
    assert "## Capability creep" not in out
