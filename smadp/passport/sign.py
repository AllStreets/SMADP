"""Passport signing — BYOK strategy + meta-tag injection.

Sigstore strategy adds in Task 8.

The signature attests to the canonical sha256 (`canonical_passport_sha256(...)`).
We do NOT sign the rendered HTML — it includes the signature itself, which would
be circular. The verifier extracts the canonical metadata payload from the
HTML's <script id="smadp-passport-payload"> tag, recomputes the canonical sha,
and checks the signature against that fixed input.
"""

from __future__ import annotations

import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _replace_meta(html: bytes, name: str, value: str) -> bytes:
    """Replace the content of a <meta name="..."> tag in-place."""
    pattern = re.compile(rb'(name="' + re.escape(name.encode()) + rb'" content=")([^"]*)(")')
    new_content = value.encode("utf-8")
    return pattern.sub(rb"\g<1>" + new_content + rb"\g<3>", html, count=1)


def inject_signature_meta(
    html: bytes,
    *,
    signature_hex: str,
    public_key_hex: str,
    signing_strategy_label: str,
    rekor_uuid: str,
    rekor_log_index: str,
    transparency_event_id: int,
    transparency_status: str,
) -> bytes:
    """Set the signing-related <meta> tags. Idempotent for fixed inputs."""
    out = html
    out = _replace_meta(out, "smadp-signature-hex", signature_hex)
    out = _replace_meta(out, "smadp-public-key-hex", public_key_hex)
    out = _replace_meta(out, "smadp-signing-strategy", signing_strategy_label)
    out = _replace_meta(out, "smadp-rekor-uuid", rekor_uuid)
    out = _replace_meta(out, "smadp-rekor-log-index", rekor_log_index)
    out = _replace_meta(out, "smadp-transparency-event-id", str(transparency_event_id))
    out = _replace_meta(out, "smadp-transparency-status", transparency_status)
    return out


def sign_unsigned_html(
    html: bytes,
    *,
    signing_key: Ed25519PrivateKey,
    canonical_sha256: str,
    signing_strategy_label: str,
    transparency_event_id: int,
    transparency_status: str,
    rekor_uuid: str,
    rekor_log_index: str,
) -> bytes:
    """Sign the canonical sha and inject all signing metadata into ``html``."""
    sig = signing_key.sign(canonical_sha256.encode("utf-8"))
    pub_bytes = signing_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    return inject_signature_meta(
        html,
        signature_hex=sig.hex(),
        public_key_hex=pub_bytes.hex(),
        signing_strategy_label=signing_strategy_label,
        rekor_uuid=rekor_uuid,
        rekor_log_index=rekor_log_index,
        transparency_event_id=transparency_event_id,
        transparency_status=transparency_status,
    )


__all__ = ["inject_signature_meta", "sign_unsigned_html"]
