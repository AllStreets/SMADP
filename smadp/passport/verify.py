"""Offline passport verifier — extract embedded payload, recompute, check sig."""

from __future__ import annotations

import json
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from smadp.passport.canonical import canonical_passport_sha256
from smadp.schemas.passport import SigningStrategy, VerificationResult

_META_RE = re.compile(
    rb'<meta name="(?P<name>[a-z0-9_\-]+)" content="(?P<value>[^"]*)"\s*/?>'
)
_PAYLOAD_RE = re.compile(
    rb'<script type="application/json" id="smadp-passport-payload">(?P<payload>.+?)</script>',
    re.DOTALL,
)


def _extract_meta(html: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _META_RE.finditer(html):
        out[m.group("name").decode()] = m.group("value").decode()
    return out


def _extract_payload(html: bytes) -> dict[str, Any] | None:
    m = _PAYLOAD_RE.search(html)
    if not m:
        return None
    try:
        loaded = json.loads(m.group("payload"))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def verify_passport(html: bytes) -> VerificationResult:
    """Verify a passport's embedded signature offline. Fail closed on any anomaly."""
    meta = _extract_meta(html)

    strategy = meta.get("smadp-signing-strategy", "")
    try:
        SigningStrategy(strategy)
    except ValueError:
        return VerificationResult(
            valid=False, reason=f"unknown signing_strategy: {strategy!r}"
        )

    sig_hex = meta.get("smadp-signature-hex", "")
    pub_hex = meta.get("smadp-public-key-hex", "")
    declared_sha = meta.get("smadp-canonical-sha256", "")

    if not sig_hex or not pub_hex or not declared_sha:
        return VerificationResult(
            valid=False, reason="missing signature, public key, or canonical sha"
        )

    payload = _extract_payload(html)
    if payload is None:
        return VerificationResult(
            valid=False, reason="missing or malformed payload script"
        )

    try:
        recomputed_sha = canonical_passport_sha256(
            verdict=payload.get("verdict", {}),
            frameworks=payload.get("frameworks", {}),
            evidence_index=payload.get("evidence_index", {}),
            rendered_at=payload.get("rendered_at", ""),
        )
    except Exception as exc:
        return VerificationResult(
            valid=False, reason=f"payload re-canonicalization failed: {exc}"
        )

    if recomputed_sha != declared_sha:
        return VerificationResult(
            valid=False,
            reason=(
                f"canonical sha mismatch: declared={declared_sha} "
                f"recomputed={recomputed_sha}"
            ),
        )

    # Signature is over declared_sha (the canonical sha string); rebuild and verify.
    try:
        sig_bytes = bytes.fromhex(sig_hex)
        pub_bytes = bytes.fromhex(pub_hex)
        pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub.verify(sig_bytes, declared_sha.encode("utf-8"))
    except (ValueError, InvalidSignature) as exc:
        return VerificationResult(
            valid=False, reason=f"signature verification failed: {exc}"
        )

    return VerificationResult(valid=True, reason=None)


__all__ = ["verify_passport"]
