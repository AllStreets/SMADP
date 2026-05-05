"""Runner reads role_a/role_b assignments from the queue row."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.config import Config
from smadp.sandbox import queue, runner


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    catalog = tmp_path / "catalog"
    cache = tmp_path / "cache"
    catalog.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMADP_CATALOG", str(catalog))
    monkeypatch.setenv("SMADP_CACHE_DIR", str(cache))
    return Config()


def test_runner_helper_returns_slugs_and_roles(tmp_config: Config) -> None:
    run_id = queue.enqueue_sandbox_run(
        slug_a="aider",
        slug_b="continue-dev",
        scenario="calendar_email",
        config=tmp_config,
    )
    slug_a, slug_b, role_a, role_b = runner._slugs_and_roles_for_run(run_id, config=tmp_config)
    assert (slug_a, slug_b) == ("aider", "continue-dev")
    assert role_a in {"calendar", "email"}
    assert role_b in {"calendar", "email"}
    assert role_a != role_b


def test_runner_helper_raises_for_unknown_run(tmp_config: Config) -> None:
    # Make sure schema exists.
    queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=tmp_config
    )
    with pytest.raises(KeyError):
        runner._slugs_and_roles_for_run("does-not-exist", config=tmp_config)


def test_runner_helper_raises_for_legacy_null_roles(tmp_config: Config) -> None:
    """Legacy rows with NULL role_a/role_b are unrunnable; surface a clear error."""
    queue.enqueue_sandbox_run(
        slug_a="aider", slug_b="continue-dev", scenario="calendar_email", config=tmp_config
    )
    import sqlite3

    db_path = tmp_config.cache_dir / "sandbox-queue.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO runs(id, slug_a, slug_b, scenario, state, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            ("legacy", "aider", "continue-dev", "calendar_email", "2025-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RuntimeError, match="missing role binding"):
        runner._slugs_and_roles_for_run("legacy", config=tmp_config)
