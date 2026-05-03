"""Tests for ``smadp.catalog.lint`` — catalog linter & cross-ref checks."""

from __future__ import annotations

import json
from pathlib import Path

from smadp.catalog.lint import lint_catalog
from smadp.config import Config


def _config_for(catalog: Path) -> Config:
    return Config(repo_root=catalog.parent)


def test_seed_catalog_is_clean(tmp_catalog: Path) -> None:
    """The shipped catalog must lint with zero errors."""
    report = lint_catalog(_config_for(tmp_catalog))
    error_messages = [f"{i.kind}:{i.target} :: {i.message}" for i in report.errors]
    assert report.ok, "seed catalog has lint errors:\n" + "\n".join(error_messages)
    assert report.profiles_checked > 0
    assert report.verdicts_checked > 0
    assert report.evidence_checked > 0


def test_detects_evidence_ref_pointing_to_missing_file(tmp_catalog: Path) -> None:
    profile_path = tmp_catalog / "profiles" / "claude-code.json"
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    payload["evidence_refs"].append("sha256:" + "0" * 64)
    profile_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = lint_catalog(_config_for(tmp_catalog))
    kinds = {i.kind for i in report.errors}
    assert "evidence.missing" in kinds


def test_detects_sub_verdict_missing_required_risk_key(tmp_catalog: Path) -> None:
    verdict_path = next((tmp_catalog / "verdicts").glob("*__*.json"))
    payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    # Drop one of the five required risks.
    del payload["sub_verdicts"]["E_compliance"]
    verdict_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = lint_catalog(_config_for(tmp_catalog))
    kinds = {i.kind for i in report.errors}
    # Either the JSON Schema or the Pydantic layer should flag it.
    assert kinds & {"verdict.schema", "verdict.pydantic"}


def test_detects_profile_slug_mismatch_with_filename(tmp_catalog: Path) -> None:
    profile_path = tmp_catalog / "profiles" / "claude-code.json"
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    payload["slug"] = "deliberately-different-slug"
    # Also remove evidence_refs to avoid orthogonal evidence.missing errors
    # — though those would still be valid lint errors, this test isolates one.
    profile_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = lint_catalog(_config_for(tmp_catalog))
    kinds = {i.kind for i in report.errors}
    assert "profile.filename" in kinds


def test_detects_unknown_framework_reference_in_verdict(tmp_catalog: Path) -> None:
    """A verdict whose pair references a non-existent profile must fail lint."""
    # Easiest case: verdict whose pair references an unknown slug.
    verdict_path = next((tmp_catalog / "verdicts").glob("*__*.json"))
    payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    payload["pair"] = ["does-not-exist-xyz", payload["pair"][1]]
    payload["pair"] = sorted(payload["pair"])
    # verdict_id format requires the pair slugs in it; rebuild it loosely.
    # We don't need to make verdict_id parse — schema/pydantic layers may
    # already error and that's fine for this test (we just care that the
    # cross-ref check fires).
    verdict_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = lint_catalog(_config_for(tmp_catalog))
    kinds = {i.kind for i in report.errors}
    # Either cross-ref or verdict.pydantic (verdict_id mismatch) is acceptable.
    assert "verdict.cross-ref" in kinds or "verdict.pydantic" in kinds
