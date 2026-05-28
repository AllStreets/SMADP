"""Queue: role_a/role_b columns + binding integrated at enqueue time."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from smadp.config import Config
from smadp.sandbox import queue
from smadp.sandbox.binding import ScenarioBindingError


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))
    return Config()


def test_enqueue_writes_role_a_and_role_b(tmp_config: Config) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider",
        slug_b="continue-dev",
        scenario="calendar_email",
        config=tmp_config,
    )
    rows = queue._all_rows_for_test(config=tmp_config)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == run_id
    assert row["role_a"] in {"calendar", "email"}
    assert row["role_b"] in {"calendar", "email"}
    assert row["role_a"] != row["role_b"]


def test_enqueue_raises_when_no_binding_fits(tmp_config: Config) -> None:
    # coding_browser requires `run_browsers`; none of our four adapters has it.
    with pytest.raises(ScenarioBindingError):
        queue.enqueue_sandbox_run(
            slug_a="aider",
            slug_b="continue-dev",
            scenario="coding_browser",
            config=tmp_config,
        )
    # No row written.
    assert queue._all_rows_for_test(config=tmp_config) == []


def test_legacy_rows_get_null_role_columns(tmp_config: Config) -> None:
    """Existing rows from before the migration are tolerated as NULL."""
    queue.enqueue_sandbox_run(
        slug_a="aider",
        slug_b="continue-dev",
        scenario="calendar_email",
        config=tmp_config,
    )
    db_path = tmp_config.cache_dir / "sandbox-queue.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO runs(id, slug_a, slug_b, scenario, state, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            ("legacy_run", "x", "y", "calendar_email", "2025-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    rows = {r["id"]: r for r in queue._all_rows_for_test(config=tmp_config)}
    assert rows["legacy_run"]["role_a"] is None
    assert rows["legacy_run"]["role_b"] is None


def test_enqueue_populates_participants_json(tmp_config: Config) -> None:
    """N-ary forward-compat: enqueue writes a participants_json blob too."""
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider",
        slug_b="continue-dev",
        scenario="calendar_email",
        config=tmp_config,
    )
    rows = {r["id"]: r for r in queue._all_rows_for_test(config=tmp_config)}
    row = rows[run_id]
    participants = queue.participants_for_row(row)
    assert len(participants) == 2
    assert {p["slug"] for p in participants} == {"aider", "continue-dev"}
    assert {p["role"] for p in participants} == {"calendar", "email"}


def test_participants_for_row_falls_back_to_pair_columns(tmp_config: Config) -> None:
    """Rows enqueued before participants_json was added still decode."""
    # Simulate a pre-migration row.
    queue.enqueue_sandbox_run(
        slug_a="aider",
        slug_b="continue-dev",
        scenario="calendar_email",
        config=tmp_config,
    )
    db_path = tmp_config.cache_dir / "sandbox-queue.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO runs(id, slug_a, slug_b, scenario, state, created_at, "
            "role_a, role_b) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (
                "legacy_run_2",
                "alpha",
                "bravo",
                "calendar_email",
                "2025-01-01T00:00:00Z",
                "calendar",
                "email",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    rows = {r["id"]: r for r in queue._all_rows_for_test(config=tmp_config)}
    legacy_row = rows["legacy_run_2"]
    # participants_json is NULL on the legacy row.
    assert legacy_row["participants_json"] is None
    parts = queue.participants_for_row(legacy_row)
    assert parts == [
        {"role": "calendar", "slug": "alpha"},
        {"role": "email", "slug": "bravo"},
    ]


def test_participants_for_row_raises_when_role_columns_null(
    tmp_config: Config,
) -> None:
    """Rows with no participants_json AND NULL role columns can't be decoded.

    These rows would have been enqueued by a pre-binding-aware runner; silently
    falling back to literal "role_a"/"role_b" sentinels would mis-wire env vars
    downstream, so we raise loudly instead.
    """
    # Need the schema to exist first; enqueue a valid row to bootstrap it.
    queue.enqueue_sandbox_run(
        slug_a="aider",
        slug_b="continue-dev",
        scenario="calendar_email",
        config=tmp_config,
    )
    db_path = tmp_config.cache_dir / "sandbox-queue.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO runs(id, slug_a, slug_b, scenario, state, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (
                "broken_legacy_run",
                "alpha",
                "bravo",
                "calendar_email",
                "2025-01-01T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    rows = {r["id"]: r for r in queue._all_rows_for_test(config=tmp_config)}
    broken_row = rows["broken_legacy_run"]
    assert broken_row["participants_json"] is None
    assert broken_row["role_a"] is None
    assert broken_row["role_b"] is None
    with pytest.raises(ValueError, match="role_a/role_b are NULL"):
        queue.participants_for_row(broken_row)
