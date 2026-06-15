"""The five-rung evidence ladder is canonical and correctly ordered."""
from __future__ import annotations

import pytest

from smadp.schemas.evidence_level import EVIDENCE_LADDER, is_at_least, rank


def test_ladder_is_exactly_five_rungs_in_order() -> None:
    assert EVIDENCE_LADDER == (
        "unverified-profile",
        "docs-only",
        "behavior-observed",
        "profile-verified",
        "sandbox-validated",
    )


def test_behavior_observed_sits_between_docs_only_and_profile_verified() -> None:
    assert rank("docs-only") < rank("behavior-observed") < rank("profile-verified")


@pytest.mark.parametrize(
    "lower,higher",
    [
        ("unverified-profile", "docs-only"),
        ("docs-only", "behavior-observed"),
        ("behavior-observed", "profile-verified"),
        ("profile-verified", "sandbox-validated"),
    ],
)
def test_strict_monotonic_ranks(lower: str, higher: str) -> None:
    assert rank(lower) < rank(higher)


def test_rank_round_trips_index() -> None:
    for i, level in enumerate(EVIDENCE_LADDER):
        assert rank(level) == i


def test_is_at_least() -> None:
    assert is_at_least("profile-verified", "behavior-observed") is True
    assert is_at_least("behavior-observed", "profile-verified") is False
    assert is_at_least("sandbox-validated", "unverified-profile") is True


def test_rank_rejects_unknown_level() -> None:
    with pytest.raises(ValueError):
        rank("totally-made-up")
