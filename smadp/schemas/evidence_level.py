"""Canonical SMADP evidence ladder — single source of truth for ordering.

The ladder is intentionally five rungs, ordered weakest->strongest:

    unverified-profile < docs-only < behavior-observed < profile-verified
    < sandbox-validated

``behavior-observed`` (added by Pillar S3.1) is the first path for a
closed-source agent to climb past ``docs-only``: its observed runtime
behavior, captured by the MCP recording proxy, is evidence even when its
source is not. Every site that compares evidence levels MUST derive its
ordering from EVIDENCE_LADDER / rank here so a future rung insertion is a
one-line change rather than a codebase-wide hunt.
"""

from __future__ import annotations

from typing import Literal

EvidenceLevel = Literal[
    "unverified-profile",
    "docs-only",
    "behavior-observed",
    "profile-verified",
    "sandbox-validated",
]

EVIDENCE_LADDER: tuple[EvidenceLevel, ...] = (
    "unverified-profile",
    "docs-only",
    "behavior-observed",
    "profile-verified",
    "sandbox-validated",
)

_RANK: dict[str, int] = {level: i for i, level in enumerate(EVIDENCE_LADDER)}


def rank(level: str) -> int:
    """Return the ordinal rank of ``level`` (0 = weakest). Raises on unknown."""
    try:
        return _RANK[level]
    except KeyError as exc:
        raise ValueError(f"unknown evidence_level: {level!r}") from exc


def is_at_least(level: str, floor: str) -> bool:
    """True iff ``level`` is at or above ``floor`` on the ladder."""
    return rank(level) >= rank(floor)


__all__ = ["EVIDENCE_LADDER", "EvidenceLevel", "is_at_least", "rank"]
