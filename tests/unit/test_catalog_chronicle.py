"""Tests for ``smadp.catalog.chronicle`` — append-only audit log."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from smadp.catalog.chronicle import Chronicle
from smadp.config import Config
from smadp.schemas.chronicle import ChronicleEvent
from smadp.utils.time import utcnow


def _config_for(catalog: Path) -> Config:
    return Config(repo_root=catalog.parent)


def test_append_creates_daily_file(tmp_catalog: Path) -> None:
    chron = Chronicle(_config_for(tmp_catalog))
    ev = ChronicleEvent(ts=utcnow(), event="profile.created", by="tests", slug="x1")
    path = chron.append(ev)
    assert path.exists()
    assert path.suffix == ".jsonl"


def test_record_helper(tmp_catalog: Path) -> None:
    chron = Chronicle(_config_for(tmp_catalog))
    path = chron.record("profile.refreshed", slug="claude-code", by="tests")
    assert path.exists()
    contents = path.read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(contents[-1])
    assert last["event"] == "profile.refreshed"
    assert last["by"] == "tests"
    assert last["slug"] == "claude-code"


def test_iter_events_reads_round_trip(tmp_catalog: Path) -> None:
    chron = Chronicle(_config_for(tmp_catalog))
    chron.record("profile.created", slug="round-trip-1", by="tests")
    events = list(chron.iter_events())
    slugs = [e.slug for e in events if e.slug]
    assert "round-trip-1" in slugs


def test_concurrent_appends_dont_corrupt(tmp_catalog: Path) -> None:
    """Run 100 threaded appends and verify exactly 100 valid lines land."""
    chron = Chronicle(_config_for(tmp_catalog))

    def _one(i: int) -> None:
        chron.record("profile.created", slug=f"thread-test-{i:03d}", by="tests")

    n = 100
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(_one, range(n)))

    # Count only the lines we just appended (slug starts with thread-test-).
    cfg = _config_for(tmp_catalog)
    found_slugs: set[str] = set()
    invalid_lines = 0
    for path in sorted(cfg.chronicle_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    invalid_lines += 1
                    continue
                slug = obj.get("slug", "")
                if isinstance(slug, str) and slug.startswith("thread-test-"):
                    found_slugs.add(slug)
    assert invalid_lines == 0, f"corrupted lines: {invalid_lines}"
    assert len(found_slugs) == n, f"expected {n} unique appends, got {len(found_slugs)}"
