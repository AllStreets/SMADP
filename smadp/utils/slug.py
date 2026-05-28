"""Slug normalization and pair canonicalization."""

from __future__ import annotations

import re
from collections.abc import Iterable

_SLUGIFY_RE = re.compile(r"[^a-z0-9]+")


def normalize_slug(s: str) -> str:
    s = s.strip().lower()
    s = _SLUGIFY_RE.sub("-", s).strip("-")
    if not s:
        raise ValueError("Slug normalizes to empty string")
    return s


def sort_pair(a: str, b: str) -> tuple[str, str]:
    if a == b:
        raise ValueError("Pair must be two different slugs")
    return (a, b) if a < b else (b, a)


def pair_filename(a: str, b: str) -> str:
    a, b = sort_pair(a, b)
    return f"{a}__{b}.json"


def all_pairs(slugs: Iterable[str]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    items = list(slugs)
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            seen.add(sort_pair(a, b))
    return sorted(seen)


def sort_participants(slugs: Iterable[str]) -> list[str]:
    """Return slugs sorted alphabetically. The canonical filename order."""
    return sorted(normalize_slug(s) for s in slugs)


def participants_filename(slugs: Iterable[str]) -> str:
    """Return the verdict filename for a participating-agents set.

    Length 2: 'alice__bob.json' (matches existing pair_filename output).
    Length 3: 'alice__bob__carol.json'.
    Length 4: 'alice__bob__carol__dan.json'.
    """
    sorted_slugs = sort_participants(slugs)
    if not (2 <= len(sorted_slugs) <= 4):
        raise ValueError(
            f"participants_filename requires 2-4 slugs, got {len(sorted_slugs)}"
        )
    if len(set(sorted_slugs)) != len(sorted_slugs):
        raise ValueError(f"participants must be unique slugs; got {sorted_slugs}")
    return "__".join(sorted_slugs) + ".json"
