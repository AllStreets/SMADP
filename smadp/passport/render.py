"""Render passport HTML (unsigned core + signed wrapper coming in Task 7)."""

from __future__ import annotations

import json
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from smadp.passport.canonical import canonical_passport_sha256
from smadp.passport.icons import LUCIDE_ICONS


def _jinja_env() -> Environment:
    return Environment(
        loader=PackageLoader("smadp.passport", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        keep_trailing_newline=False,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _icons_for_template() -> dict[str, str]:
    """Lucide SVGs with a passport-icon class injected for the template."""
    from smadp.passport.icons import render_icon

    return {name: render_icon(name, css_class="passport-icon") for name in LUCIDE_ICONS}


def _render_unsigned(
    *,
    verdict: dict[str, Any],
    frameworks: dict[str, Any],
    evidence_index: dict[str, Any],
    evidence_blobs_b64: str,
    rendered_at: str,
) -> bytes:
    """Render the deterministic body of a passport, with empty signing fields."""
    env = _jinja_env()
    tpl = env.get_template("passport.html.j2")

    canonical_sha = canonical_passport_sha256(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        rendered_at=rendered_at,
    )

    metadata_payload = {
        "verdict": verdict,
        "frameworks": frameworks,
        "evidence_index": evidence_index,
        "rendered_at": rendered_at,
    }
    metadata_json = json.dumps(
        metadata_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )

    out = tpl.render(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        metadata_json=metadata_json,
        rendered_at=rendered_at,
        signing_strategy_label="byok",
        signature_hex="",
        public_key_hex="",
        canonical_sha256=canonical_sha,
        rekor_uuid="",
        rekor_log_index="",
        transparency_event_id=0,
        transparency_status="local",
        icons=_icons_for_template(),
        evidence_blobs_b64=evidence_blobs_b64,
    )
    return out.encode("utf-8")


__all__ = ["_jinja_env", "_render_unsigned"]
