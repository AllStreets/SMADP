"""Envelope construction + HMAC-SHA256 signing for webhook deliveries."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from smadp.schemas.webhooks import EventType, WebhookEnvelope


def build_envelope(
    *,
    event_id: str,
    event_type: EventType,
    created_at: datetime,
    workspace_id: str,
    data: dict[str, Any],
    signature_meta: dict[str, Any],
) -> WebhookEnvelope:
    """Construct a validated ``WebhookEnvelope``."""
    return WebhookEnvelope(
        id=event_id,
        type=event_type,
        created_at=created_at,
        workspace_id=workspace_id,
        data=data,
        signature_meta=signature_meta,
    )


def canonical_envelope_bytes(envelope: WebhookEnvelope) -> bytes:
    """Sorted-keys, compact UTF-8 JSON. Deterministic byte-for-byte."""
    blob = envelope.model_dump(mode="json")
    return json.dumps(
        blob,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_hmac(secret: str, body: bytes) -> str:
    """Return ``sha256=<hex>`` for the X-SMADP-Signature header."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


__all__ = [
    "build_envelope",
    "canonical_envelope_bytes",
    "compute_hmac",
]
