"""Smoke test: Jinja2 environment finds and parses the passport template."""

from __future__ import annotations

from smadp.passport.render import _jinja_env


def test_passport_template_loads_and_parses():
    env = _jinja_env()
    tpl = env.get_template("passport.html.j2")
    out = tpl.render(
        verdict={"verdict_id": "vdt_X", "headline": "Test"},
        frameworks={},
        evidence_index={},
        metadata_json="{}",
        rendered_at="2026-05-03T00:00:00Z",
        signing_strategy_label="byok",
        signature_hex="abc",
        public_key_hex="def",
        canonical_sha256="sha256:" + "0" * 64,
        rekor_uuid="",
        rekor_log_index="",
        transparency_event_id=1,
        transparency_status="local",
        icons={"shield": "<svg></svg>"},
        evidence_blobs_b64="e30=",
    )
    assert "<!DOCTYPE html>" in out
    assert "vdt_X" in out
    assert "smadp-canonical-sha256" in out
