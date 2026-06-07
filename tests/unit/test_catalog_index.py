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
    # Indexer dedupes by slug (a slug that exists in both catalog/profiles/
    # and catalog/profiles/_unverified/ is indexed once, with the verified
    # entry winning per Repo.iter_profile_entries). The expected count is
    # therefore unique-slug profiles + verdicts.
    seen_slugs: set[str] = set()
    for root in [tmp_catalog / "profiles", tmp_catalog / "profiles" / "_unverified"]:
        for p in root.glob("*.json"):
            seen_slugs.add(p.stem)
    verdicts = list((tmp_catalog / "verdicts").glob("*__*.json"))
    assert count == len(seen_slugs) + len(verdicts)


def test_search_for_claude_code_returns_claude_code(tmp_catalog: Path) -> None:
    # Originally the test searched for the bare keyword "claude" — but the
    # autopilot pivot brought in hundreds of ONEXUS stubs whose slugs also
    # contain "claude" (claude-coder, ai-marketing-claude, …), so bm25 no
    # longer guarantees claude-code in the top-K. The hand-curated profile is
    # still findable via the specific query "claude-code".
    idx = CatalogIndex(_config_for(tmp_catalog))
    idx.rebuild()
    hits = idx.search("claude-code", limit=20)
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
