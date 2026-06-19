"""Tests for ``smadp.catalog.repo`` — atomic CRUD over the catalog."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config


def _config_for(catalog: Path) -> Config:
    return Config(repo_root=catalog.parent)


# ----------------------------------------------------------------- profiles
def test_load_profile_round_trip(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    p = repo.load_profile("claude-code")
    assert p.slug == "claude-code"
    assert p.name == "Claude Code"


def test_save_profile_writes_and_reloads(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    p = repo.load_profile("claude-code")
    # Modify a non-validated field to confirm the new bytes round-trip.
    new_p = p.model_copy(update={"name": "Claude Code Updated"})
    path = repo.save_profile(new_p, verified=True)
    assert path.exists()
    reloaded = repo.load_profile("claude-code")
    assert reloaded.name == "Claude Code Updated"


def test_profile_exists(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    assert repo.profile_exists("claude-code")
    assert not repo.profile_exists("does-not-exist-xyz")


def test_load_missing_profile_raises(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    with pytest.raises(NotFoundError):
        repo.load_profile("does-not-exist-xyz")


# ----------------------------------------------------------- atomic writes
def test_atomic_write_no_partial_file_on_failure(tmp_catalog: Path) -> None:
    """If json.dump raises mid-write, no partial file should remain at the target."""
    repo = CatalogRepo(_config_for(tmp_catalog))
    p = repo.load_profile("claude-code")
    target_path = repo.profile_path("claude-code", verified=True)
    # Snapshot the current file contents
    original_bytes = target_path.read_bytes()

    with patch(
        "smadp.catalog.repo.json.dump",
        side_effect=RuntimeError("simulated disk failure"),
    ):
        with pytest.raises(RuntimeError, match="simulated disk failure"):
            repo.save_profile(p)

    # The target file must still hold the original bytes — not be partial.
    assert target_path.read_bytes() == original_bytes
    # No leftover .tmp file should be lingering in the directory.
    leftovers = list(target_path.parent.glob(f".{target_path.name}.*.tmp"))
    assert leftovers == [], f"unexpected tmp leftovers: {leftovers}"


# ------------------------------------------------------------------ verdicts
def test_verdict_filename_alphabetized(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    # For a pair with no existing file, verdict_path returns the canonical
    # alphabetized name, independent of input order.
    p1 = repo.verdict_path("zebra-agent", "alpha-agent")
    p2 = repo.verdict_path("alpha-agent", "zebra-agent")
    assert p1 == p2
    assert p1.name == "alpha-agent__zebra-agent.json"
    # An existing verdict also resolves order-independently to the same file.
    assert repo.verdict_path("cursor", "claude-code") == repo.verdict_path("claude-code", "cursor")
    assert repo.verdict_path("claude-code", "cursor").exists()


def test_load_verdict_from_either_order(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    v1 = repo.load_verdict("claude-code", "cursor")
    v2 = repo.load_verdict("cursor", "claude-code")
    assert v1.verdict_id == v2.verdict_id
    # And the on-disk pair is alphabetized.
    assert tuple(v1.pair) == ("claude-code", "cursor")


def test_save_verdict_alphabetized_filename(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    # Re-key an existing verdict onto a fresh pair (no existing file) so the new
    # write lands on the canonical alphabetized filename.
    src = repo.load_verdict("claude-code", "cursor")
    v = src.model_copy(
        update={
            "pair": ("alpha-agent", "zebra-agent"),
            "participants": ["alpha-agent", "zebra-agent"],
        }
    )
    path = repo.save_verdict(v)
    assert path.name == "alpha-agent__zebra-agent.json"
    # Reload from disk to confirm round-trip.
    v2 = repo.load_verdict("alpha-agent", "zebra-agent")
    assert v2.verdict_id == v.verdict_id


def test_list_profiles_returns_seed(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    profiles = repo.list_profiles()
    slugs = {p.slug for p in profiles}
    assert "claude-code" in slugs
    # Profiles are alphabetized.
    assert [p.slug for p in profiles] == sorted(p.slug for p in profiles)


def test_list_verdicts_returns_seed(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    verdicts = repo.list_verdicts()
    pairs = {tuple(v.pair) for v in verdicts}
    assert ("claude-code", "cursor") in pairs


# ----------------------------------------------------------------- evidence
def test_load_evidence(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    refs = list(repo.iter_evidence_refs())
    assert refs, "no evidence refs found"
    e = repo.load_evidence(refs[0])
    assert e.evidence_ref == refs[0]


def test_evidence_path_strips_prefix(tmp_catalog: Path) -> None:
    repo = CatalogRepo(_config_for(tmp_catalog))
    plain_sha = "0" * 64
    p1 = repo.evidence_path(f"sha256:{plain_sha}")
    p2 = repo.evidence_path(plain_sha)
    assert p1 == p2
    assert p1.name == f"sha256-{plain_sha}.json"


def test_verdict_path_resolves_versioned_filename(tmp_catalog: Path) -> None:
    """A verdict written under the versioned ``v_<date>_<a>__<b>_<hash>.json``
    name must be discoverable, not just the canonical ``<a>__<b>.json``.
    Regression: promote_from_run seeded a duplicate pending verdict instead of
    promoting the existing versioned one."""
    import json

    repo = CatalogRepo(_config_for(tmp_catalog))
    vdir = tmp_catalog / "verdicts"
    assert not (vdir / "omega__zeta.json").exists()  # no canonical file
    seed = next(p for p in vdir.glob("*__*.json") if not p.name.endswith(".sig.json"))
    doc = json.loads(seed.read_text("utf-8"))
    doc["pair"] = ["omega", "zeta"]
    doc["participants"] = ["omega", "zeta"]
    versioned = vdir / "v_2026-06-10_omega__zeta_abc123.json"
    versioned.write_text(json.dumps(doc), encoding="utf-8")

    assert repo.verdict_exists("omega", "zeta")
    assert repo.verdict_path("omega", "zeta") == versioned
    assert tuple(repo.load_verdict("omega", "zeta").pair) == ("omega", "zeta")
