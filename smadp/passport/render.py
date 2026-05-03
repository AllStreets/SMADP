"""Render passport HTML (unsigned core + signed wrapper)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from smadp.config import Config, load_config
from smadp.passport.canonical import canonical_passport_sha256
from smadp.passport.icons import LUCIDE_ICONS, render_icon
from smadp.passport.sign import sign_unsigned_html
from smadp.schemas.passport import SigningStrategy
from smadp.tenancy import keys
from smadp.transparency import journal
from smadp.transparency import sigstore as _sigstore
from smadp.webhooks import dispatcher
from smadp.schemas.webhooks import EventType as _WebhookEventType


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


def _utcnow_isoformat_seconds() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _evidence_blobs_b64(evidence_blobs: dict[str, dict[str, Any]]) -> str:
    """Base64-encode the JSON serialization of all evidence blobs."""
    if not evidence_blobs:
        return ""
    payload = json.dumps(evidence_blobs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def render_passport(
    *,
    verdict: dict[str, Any],
    frameworks: dict[str, Any],
    evidence_index: dict[str, Any],
    evidence_blobs: dict[str, dict[str, Any]],
    signing_strategy: SigningStrategy,
    workspace_id: str,
    rendered_at: str | None = None,
    config: Config | None = None,
) -> bytes:
    """Render a fully signed passport.

    Steps:
    1. Load the workspace's BYOK key (raise KeyError if missing).
    2. Compute the canonical sha256 over (verdict, frameworks, evidence_index, ts).
    3. Append a ``passport.generated`` transparency event signed by the same key.
    4. (SIGSTORE strategy only, gated by SMADP_SIGSTORE_ENABLED) submit the signed
       canonical sha to Rekor; on success embed UUID + log_index, on failure
       fall back to ``deferred`` status.
    5. Render the unsigned HTML, then inject all signing metadata.
    """
    cfg = config or load_config()
    ts = rendered_at or _utcnow_isoformat_seconds()

    signing_key = keys.load_signing_key(workspace_id=workspace_id, config=cfg)
    if signing_key is None:
        raise KeyError(f"byok_key_missing_for_workspace: {workspace_id}")

    canonical_sha = canonical_passport_sha256(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        rendered_at=ts,
    )

    transparency_event = journal.append_event(
        event_type="passport.generated",
        payload={
            "workspace_id": workspace_id,
            "verdict_id": verdict.get("verdict_id"),
            "canonical_sha256": canonical_sha,
            "signing_strategy": signing_strategy.value,
        },
        signing_key=signing_key,
        config=cfg,
    )

    # Fire passport.generated webhook to all matching subscriptions.
    # The transparency event id is the binding between log and webhook.
    dispatcher.dispatch_event(
        event_type=_WebhookEventType.PASSPORT_GENERATED,
        payload={
            "verdict_id": verdict.get("verdict_id"),
            "workspace_id": workspace_id,
            "canonical_sha256": canonical_sha,
            "signing_strategy": signing_strategy.value,
        },
        workspace_id=workspace_id,
        signature_meta={
            "transparency_log_id": transparency_event.id,
            "prev_event_hash": transparency_event.prev_hash,
        },
        config=cfg,
    )

    rekor_uuid = ""
    rekor_log_index = ""
    transparency_status = "local"
    if signing_strategy == SigningStrategy.SIGSTORE:
        if _sigstore._enabled():
            pub_pem_bytes = signing_key.public_key().public_bytes(
                encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
            )
            pub_pem = pub_pem_bytes.decode("ascii")
            sig_hex = signing_key.sign(canonical_sha.encode("utf-8")).hex()
            uuid = _sigstore.submit_signed_payload(
                signing_input=canonical_sha.encode("utf-8"),
                signature_hex=sig_hex,
                public_key_pem=pub_pem,
            )
            if uuid:
                proof = _sigstore.get_inclusion_proof(uuid, config=cfg)
                rekor_uuid = uuid
                rekor_log_index = str(proof.get("logIndex", "")) if proof else ""
                transparency_status = "submitted"
            else:
                transparency_status = "deferred"
        else:
            transparency_status = "deferred"

    unsigned = _render_unsigned(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        evidence_blobs_b64=_evidence_blobs_b64(evidence_blobs),
        rendered_at=ts,
    )
    return sign_unsigned_html(
        unsigned,
        signing_key=signing_key,
        canonical_sha256=canonical_sha,
        signing_strategy_label=signing_strategy.value,
        transparency_event_id=transparency_event.id,
        transparency_status=transparency_status,
        rekor_uuid=rekor_uuid,
        rekor_log_index=rekor_log_index,
    )


__all__ = ["_jinja_env", "_render_unsigned", "render_passport"]
