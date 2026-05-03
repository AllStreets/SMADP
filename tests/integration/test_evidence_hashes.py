"""Verify the content-addressed integrity of every evidence file.

Each evidence file lives at ``catalog/_evidence/sha256-<hex>.json``. The
in-file ``sha256`` field MUST equal the ``<hex>`` portion of the filename,
AND it MUST equal ``sha256_text(quote)`` — the contract enforced by
``smadp.profiler.extractor.store_evidence``. If either invariant breaks,
the evidence cannot be trusted as reproducible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smadp.utils.hashing import sha256_text


@pytest.fixture(scope="session")
def evidence_records(all_evidence_paths: list[Path]) -> list[tuple[Path, dict]]:
    records: list[tuple[Path, dict]] = []
    for path in all_evidence_paths:
        with path.open("r", encoding="utf-8") as fh:
            records.append((path, json.load(fh)))
    return records


def test_every_filename_matches_in_file_sha(evidence_records: list[tuple[Path, dict]]) -> None:
    assert evidence_records, "no evidence files to check"
    for path, data in evidence_records:
        expected = path.stem.removeprefix("sha256-")
        assert data["sha256"] == expected, (
            f"filename/in-file sha mismatch in {path.name}: "
            f"file={data['sha256']!r} filename={expected!r}"
        )


def test_every_sha_matches_quote_text(evidence_records: list[tuple[Path, dict]]) -> None:
    """The sha256 field is computed from the verbatim quote text."""
    assert evidence_records
    mismatches: list[str] = []
    for path, data in evidence_records:
        expected = sha256_text(data["quote"])
        if data["sha256"] != expected:
            mismatches.append(f"{path.name}: stored={data['sha256']} expected={expected}")
    assert not mismatches, (
        f"{len(mismatches)} evidence files have hash != sha256(quote):\n"
        + "\n".join(mismatches[:5])
    )
