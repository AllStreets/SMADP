"""Every committed chain fixture loads, validates, and references real profiles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.schemas import Chain

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAINS = REPO_ROOT / "catalog" / "chains"
PROFILES = REPO_ROOT / "catalog" / "profiles"


def _all_known_slugs() -> set[str]:
    slugs = {p.stem for p in PROFILES.glob("*.json")}
    slugs |= {p.stem for p in (PROFILES / "_unverified").glob("*.json")}
    return slugs


@pytest.mark.parametrize("path", sorted(CHAINS.glob("*.json")))
def test_chain_validates(path: Path) -> None:
    chain = Chain.model_validate(json.loads(path.read_text("utf-8")))
    assert path.stem == chain.chain_id


def test_at_least_six_chains() -> None:
    assert len(list(CHAINS.glob("*.json"))) >= 6


def test_chain_participants_resolve_to_profiles() -> None:
    known = _all_known_slugs()
    for path in CHAINS.glob("*.json"):
        chain = Chain.model_validate(json.loads(path.read_text("utf-8")))
        for p in chain.participants:
            assert p.slug in known, f"{chain.chain_id} references unknown {p.slug}"
