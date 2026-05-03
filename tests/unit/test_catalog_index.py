"""Tests for ``smadp.catalog.index`` — SQLite FTS5 search index."""

from __future__ import annotations

from pathlib import Path

from smadp.catalog.index import CatalogIndex
from smadp.config import Config


def _config_for(catalog: Path) -> Config:
    return Config(repo_root=catalog.parent)


def test_rebuild_indexes_all_profiles_and_verdicts(tmp_catalog: Path) -> None:
    idx = CatalogIndex(_config_for(tmp_catalog))
    count = idx.rebuild()
    assert count > 0
    # We expect at least the profile + verdict counts shipped with seed data.
    profiles = list((tmp_catalog / "profiles").glob("*.json"))
    verdicts = list((tmp_catalog / "verdicts").glob("*__*.json"))
    assert count == len(profiles) + len(verdicts)


def test_search_for_claude_returns_claude_code(tmp_catalog: Path) -> None:
    idx = CatalogIndex(_config_for(tmp_catalog))
    idx.rebuild()
    hits = idx.search("claude", limit=20)
    refs = {(h.kind, h.ref) for h in hits}
    assert ("profile", "claude-code") in refs


def test_search_empty_query_returns_empty(tmp_catalog: Path) -> None:
    idx = CatalogIndex(_config_for(tmp_catalog))
    idx.rebuild()
    assert idx.search("") == []
    assert idx.search("   ") == []


def test_search_lazy_rebuild(tmp_catalog: Path) -> None:
    """search() should auto-rebuild if no DB exists yet."""
    idx = CatalogIndex(_config_for(tmp_catalog))
    # Make sure no DB lingers.
    if idx.db_path.exists():
        idx.db_path.unlink()
    hits = idx.search("claude", limit=5)
    assert hits, "search returned no hits even after lazy rebuild"
