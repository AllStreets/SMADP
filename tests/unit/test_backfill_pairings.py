"""build_table is symmetric, sorted, and orphan-aware."""

from __future__ import annotations

from pathlib import Path

from scripts.v2_e.pairings_table import PAIRS, build_table

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES = REPO_ROOT / "catalog" / "profiles"


def test_table_is_symmetric() -> None:
    table = build_table()
    for a, partners in table.items():
        for b in partners:
            assert a in table[b], f"{a} not in {b}'s pairings"


def test_table_sorted_lists() -> None:
    table = build_table()
    for slug, partners in table.items():
        assert partners == sorted(partners)


def test_no_self_pairs() -> None:
    table = build_table()
    for slug, partners in table.items():
        assert slug not in partners


def test_every_existing_slug_is_covered() -> None:
    """Every profile slug in the catalog must appear in PAIRS."""
    on_disk_slugs = set()
    for path in list(PROFILES.glob("*.json")) + list((PROFILES / "_unverified").glob("*.json")):
        on_disk_slugs.add(path.stem)
    pair_slugs = {s for ab in PAIRS for s in ab}
    missing = on_disk_slugs - pair_slugs
    assert not missing, f"slugs not in PAIRS: {sorted(missing)}"
