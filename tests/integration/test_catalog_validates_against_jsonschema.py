"""Validate every catalog file against the on-disk JSON Schema (draft 2020-12).

This is the authoritative cross-check between Pydantic models and the
public JSON Schema documents that downstream consumers depend on. Both
must agree on every seed file in the catalog.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


@pytest.fixture(scope="session")
def profile_validator(schema_dir: Path) -> Draft202012Validator:
    schema = json.loads((schema_dir / "profile.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@pytest.fixture(scope="session")
def verdict_validator(schema_dir: Path) -> Draft202012Validator:
    schema = json.loads((schema_dir / "verdict.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@pytest.fixture(scope="session")
def evidence_validator(schema_dir: Path) -> Draft202012Validator:
    schema = json.loads((schema_dir / "evidence.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@pytest.fixture(scope="session")
def chronicle_validator(schema_dir: Path) -> Draft202012Validator:
    schema = json.loads((schema_dir / "chronicle.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _iter_errors(validator: Draft202012Validator, doc: dict) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}"
        for e in validator.iter_errors(doc)
    ]


def test_every_profile_matches_schema(
    all_profile_paths: list[Path], profile_validator: Draft202012Validator
) -> None:
    assert all_profile_paths
    failures: list[str] = []
    for path in all_profile_paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        errs = _iter_errors(profile_validator, doc)
        if errs:
            failures.append(f"{path.name}:\n  - " + "\n  - ".join(errs))
    assert not failures, "schema violations:\n" + "\n".join(failures)


def test_every_verdict_matches_schema(
    all_verdict_paths: list[Path], verdict_validator: Draft202012Validator
) -> None:
    assert all_verdict_paths
    failures: list[str] = []
    for path in all_verdict_paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        errs = _iter_errors(verdict_validator, doc)
        if errs:
            failures.append(f"{path.name}:\n  - " + "\n  - ".join(errs))
    assert not failures, "schema violations:\n" + "\n".join(failures)


def test_every_evidence_matches_schema(
    all_evidence_paths: list[Path], evidence_validator: Draft202012Validator
) -> None:
    assert all_evidence_paths
    failures: list[str] = []
    for path in all_evidence_paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        errs = _iter_errors(evidence_validator, doc)
        if errs:
            failures.append(f"{path.name}:\n  - " + "\n  - ".join(errs))
    assert not failures, "schema violations:\n" + "\n".join(failures)


def test_every_chronicle_line_matches_schema(
    all_chronicle_paths: list[Path], chronicle_validator: Draft202012Validator
) -> None:
    assert all_chronicle_paths
    failures: list[str] = []
    total = 0
    for path in all_chronicle_paths:
        with path.open("r", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                doc = json.loads(raw)
                errs = _iter_errors(chronicle_validator, doc)
                if errs:
                    failures.append(
                        f"{path.name}:{lineno}:\n  - " + "\n  - ".join(errs)
                    )
                total += 1
    assert total > 0, "no chronicle lines found"
    assert not failures, "schema violations:\n" + "\n".join(failures)
