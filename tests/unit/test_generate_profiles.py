"""generate_profiles produces lint-clean, deterministic output."""

from __future__ import annotations

from pathlib import Path

from scripts.v2_e.generate_profiles import build_profile, write_all
from scripts.v2_e.ontology import SEEDS
from smadp.schemas import Profile


def test_seed_count_is_70() -> None:
    assert len(SEEDS) == 70


def test_each_seed_round_trips_via_pydantic() -> None:
    for seed in SEEDS:
        Profile.model_validate(build_profile(seed))


def test_write_all_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "profiles"
    w1, s1 = write_all(out, force=False)
    w2, s2 = write_all(out, force=False)
    assert w1 == 70 and s1 == 0
    assert w2 == 0 and s2 == 70


def test_write_all_force_overwrites(tmp_path: Path) -> None:
    out = tmp_path / "profiles"
    write_all(out, force=False)
    w, _ = write_all(out, force=True)
    assert w == 70


def test_output_is_byte_stable(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    write_all(out_a, force=False)
    write_all(out_b, force=False)
    for seed in SEEDS:
        a = (out_a / f"{seed['slug']}.json").read_bytes()
        b = (out_b / f"{seed['slug']}.json").read_bytes()
        assert a == b
