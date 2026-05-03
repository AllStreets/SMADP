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
