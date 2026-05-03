"""Tests for ``smadp.utils.time`` — UTC-only time helpers."""

from __future__ import annotations

import re
from datetime import UTC

from smadp.utils.time import utcnow, utcnow_iso

ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_utcnow_is_aware_and_utc() -> None:
    now = utcnow()
    assert now.tzinfo is not None
    # Compare offsets, not the timezone object identity, since pytz/zoneinfo
    # both yield offset-zero objects but aren't ``is`` equal to ``timezone.utc``.
    assert now.utcoffset() == UTC.utcoffset(now)


def test_utcnow_iso_ends_with_z() -> None:
    s = utcnow_iso()
    assert s.endswith("Z")
    assert "+00:00" not in s
    assert ISO_Z_RE.match(s), f"unexpected ISO format: {s!r}"


def test_utcnow_iso_is_seconds_resolution() -> None:
    s = utcnow_iso()
    # No fractional seconds
    assert "." not in s
