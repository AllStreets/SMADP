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
    for _slug, partners in table.items():
        assert partners == sorted(partners)


def test_no_self_pairs() -> None:
    table = build_table()
    for slug, partners in table.items():
        assert slug not in partners


def test_every_curated_slug_is_covered() -> None:
    """Every hand-curated (manual: true) profile must appear in PAIRS.

    PAIRS is the editorial table for the curated tier. The autopilot's
    PairGatePlanner does its own pair selection over the broader catalog
    (ONEXUS stubs + LLM-enriched docs-only profiles) and does NOT read PAIRS,
    so we only assert coverage for the curated set here.
    """
    import json

    curated_slugs: set[str] = set()
    for path in PROFILES.glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("manual") is True:
            curated_slugs.add(path.stem)
    # Hand-curated _unverified seeds count as catalog members PAIRS authored
    # against. Auto-synced seeds from the ONEXUS-Agents bridge also land here
    # but are NOT editorial — they carry an `onexus` provenance block and are
    # paired by the autopilot's PairGatePlanner once promoted, never by PAIRS.
    for path in (PROFILES / "_unverified").glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (data.get("onexus") or {}).get("sourced_from") == "ONEXUS-Agents":
            continue
        curated_slugs.add(path.stem)

    pair_slugs = {s for ab in PAIRS for s in ab}
    missing = curated_slugs - pair_slugs
    assert not missing, f"curated slugs not in PAIRS: {sorted(missing)}"
