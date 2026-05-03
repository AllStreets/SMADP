"""Tests for passport.render._render_unsigned (the deterministic body)."""

from __future__ import annotations

from smadp.passport.render import _render_unsigned


def _verdict_dict():
    return {
        "verdict_id": "vdt_FIXED",
        "pair": ["a/x", "b/y"],
        "headline": "Test verdict",
        "composite_score": 0.42,
        "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
    }


def test_render_unsigned_returns_html_bytes():
    html = _render_unsigned(
        verdict=_verdict_dict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={"sha256:abc": {"source_url": "https://x"}},
        evidence_blobs_b64="eyJzb21lIjoiZGF0YSJ9",
        rendered_at="2026-05-03T12:34:56Z",
    )
    assert isinstance(html, bytes)
    text = html.decode("utf-8")
    assert "<!DOCTYPE html>" in text
    assert "vdt_FIXED" in text
    assert "NIST AI RMF" in text
    assert "GOVERN-1.1" in text
    assert "smadp-canonical-sha256" in text


def test_render_unsigned_metadata_placeholders_are_empty():
    """Unsigned render uses empty signature/key/rekor placeholders."""
    html = _render_unsigned(
        verdict=_verdict_dict(),
        frameworks={},
        evidence_index={},
        evidence_blobs_b64="",
        rendered_at="2026-05-03T12:34:56Z",
    ).decode("utf-8")
    assert 'name="smadp-signature-hex" content=""' in html
    assert 'name="smadp-public-key-hex" content=""' in html
    assert 'name="smadp-rekor-uuid" content=""' in html
    assert 'name="smadp-transparency-status" content="local"' in html


def test_render_unsigned_is_deterministic_for_fixed_inputs():
    a = _render_unsigned(
        verdict=_verdict_dict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={"sha256:abc": {"source_url": "https://x"}},
        evidence_blobs_b64="eyJzb21lIjoiZGF0YSJ9",
        rendered_at="2026-05-03T12:34:56Z",
    )
    b = _render_unsigned(
        verdict=_verdict_dict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={"sha256:abc": {"source_url": "https://x"}},
        evidence_blobs_b64="eyJzb21lIjoiZGF0YSJ9",
        rendered_at="2026-05-03T12:34:56Z",
    )
    assert a == b
