"""Golden test: structural skeleton of a passport is byte-stable.

Strips signing-related <meta> contents (which are non-deterministic) and
compares the rest byte-for-byte.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from smadp.passport.render import _render_unsigned


_VOLATILE_META = [
    b"smadp-signature-hex",
    b"smadp-public-key-hex",
    b"smadp-rekor-uuid",
    b"smadp-rekor-log-index",
    b"smadp-transparency-event-id",
    b"smadp-transparency-status",
]


def _strip_volatile(html: bytes) -> bytes:
    """Erase the content of meta tags that vary across runs."""
    out = html
    for name in _VOLATILE_META:
        out = re.sub(
            rb'(name="' + re.escape(name) + rb'" content=")[^"]*(")',
            rb'\g<1>\g<2>',
            out,
        )
    return out


def test_unsigned_render_skeleton_is_byte_stable() -> None:
    """Test that _render_unsigned produces byte-stable output (volatile fields stripped)."""
    kwargs = {
        "verdict": {
            "verdict_id": "vdt_GOLDEN",
            "pair": ["a/x", "b/y"],
            "headline": "Golden",
            "composite_score": 0.5,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
        },
        "frameworks": {"nist_ai_rmf": {"name": "NIST AI RMF"}},
        "evidence_index": {},
        "evidence_blobs_b64": "",
        "rendered_at": "2026-05-03T12:34:56Z",
    }

    a = _render_unsigned(**kwargs)
    b = _render_unsigned(**kwargs)

    assert _strip_volatile(a) == _strip_volatile(b)


def test_full_passport_skeleton_is_byte_stable_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that full fixture passport is byte-stable across separate builds."""
    from tests.fixtures.passport.build_fixture import build_fixture_passport

    # First build
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "a"))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    a = build_fixture_passport(tmp_path / "a")

    # Second build with different cache/key paths
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "b"))
    b = build_fixture_passport(tmp_path / "b")

    assert _strip_volatile(a) == _strip_volatile(b)
