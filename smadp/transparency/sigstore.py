"""Sigstore/Rekor submission for transparency events.

Plan 1 shipped a stub. Plan 2 wires real REST calls to Rekor when
``SMADP_SIGSTORE_ENABLED=true``. Endpoint configurable via
``SMADP_REKOR_URL`` (default ``https://rekor.sigstore.dev``).

We use the ``hashedrekord`` v0.0.1 entry kind so we can submit pre-signed
events without exposing the private key. Rekor verifies the signature on
submission and, on success, returns the entry UUID.

Two entry points:

* ``submit_to_rekor(event_id=...)`` — gated by ``SMADP_SIGSTORE_ENABLED``;
  used by the journal retry path. Per-workspace public-key wiring lands
  in a later plan, so for now this uses a placeholder PEM.
* ``submit_signed_payload(...)`` — primary entry point used by the passport
  renderer. Does NOT consult ``SMADP_SIGSTORE_ENABLED`` (caller gates).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

import httpx
import structlog

from smadp.config import Config, load_config
from smadp.schemas.transparency import SignedEvent
from smadp.transparency.journal import (
    _canonical_signing_input,
    _connect,
    _ensure_schema,
    iter_events,
)

log = structlog.get_logger(__name__)

DEFAULT_REKOR_URL = "https://rekor.sigstore.dev"
SUBMIT_TIMEOUT_S = 10.0
PROOF_TIMEOUT_S = 10.0

# TODO(plan-3+): wire per-workspace public key tracking on signed_events so
# this placeholder can go away. For now Rekor will reject in production but
# tests mock the POST so it's fine for the in-flight path.
_PLACEHOLDER_PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n"
    "-----END PUBLIC KEY-----"
)


def _enabled() -> bool:
    return os.environ.get("SMADP_SIGSTORE_ENABLED", "false").lower() == "true"


def _rekor_url() -> str:
    return os.environ.get("SMADP_REKOR_URL", DEFAULT_REKOR_URL).rstrip("/")


def _build_hashedrekord_body(
    *, signing_input: bytes, signature_hex: str, public_key_pem: str
) -> dict[str, Any]:
    """Build a Rekor ``hashedrekord`` v0.0.1 entry body."""
    sha = hashlib.sha256(signing_input).hexdigest()
    return {
        "apiVersion": "0.0.1",
        "kind": "hashedrekord",
        "spec": {
            "data": {"hash": {"algorithm": "sha256", "value": sha}},
            "signature": {
                "content": base64.b64encode(bytes.fromhex(signature_hex)).decode(),
                "publicKey": {"content": base64.b64encode(public_key_pem.encode()).decode()},
            },
        },
    }


def _post_entry(body: dict[str, Any]) -> str | None:
    """POST to ``/api/v1/log/entries``; return the (sole) UUID key from response."""
    url = f"{_rekor_url()}/api/v1/log/entries"
    try:
        with httpx.Client(timeout=SUBMIT_TIMEOUT_S) as client:
            resp = client.post(url, json=body)
    except httpx.HTTPError as exc:
        log.warning("transparency.sigstore.network_error", error=str(exc))
        return None
    if resp.status_code >= 500:
        return None
    if resp.status_code == 409:
        try:
            data = resp.json()
            uuid_str = next(iter(data.keys()))
            return str(uuid_str)
        except (json.JSONDecodeError, StopIteration):
            return None
    if resp.status_code not in (200, 201):
        log.warning(
            "transparency.sigstore.bad_status",
            status=resp.status_code,
            body=resp.text[:200],
        )
        return None
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data:
        return None
    uuid_str = next(iter(data.keys()))
    return str(uuid_str)


def submit_to_rekor(*, event_id: int, config: Config | None = None) -> str | None:
    """Submit a journal event to Rekor; return UUID on success, None otherwise.

    Returns None when:
    - ``SMADP_SIGSTORE_ENABLED`` is not ``true`` (default)
    - The event is not found
    - Rekor returns 5xx or the request fails

    Uses a placeholder public key — per-workspace key wiring lands in a
    later plan. The passport renderer should call ``submit_signed_payload``
    directly instead, where the real key is available.
    """
    if not _enabled():
        log.info("transparency.sigstore.disabled", event_id=event_id)
        return None
    cfg = config or load_config()
    target: SignedEvent | None = None
    for ev in iter_events(config=cfg):
        if ev.id == event_id:
            target = ev
            break
    if target is None:
        return None
    signing_input = _canonical_signing_input(target)
    body = _build_hashedrekord_body(
        signing_input=signing_input,
        signature_hex=target.signature,
        public_key_pem=_PLACEHOLDER_PUBLIC_KEY_PEM,
    )
    return _post_entry(body)


def submit_signed_payload(
    *, signing_input: bytes, signature_hex: str, public_key_pem: str
) -> str | None:
    """Submit a pre-signed payload to Rekor; return UUID on success, None on failure.

    Primary entry point used by the passport renderer. Does NOT consult
    ``SMADP_SIGSTORE_ENABLED`` — the caller gates.
    """
    body = _build_hashedrekord_body(
        signing_input=signing_input,
        signature_hex=signature_hex,
        public_key_pem=public_key_pem,
    )
    return _post_entry(body)


def get_inclusion_proof(rekor_uuid: str, *, config: Config | None = None) -> dict[str, Any] | None:
    """Fetch the inclusion proof for a Rekor entry by UUID.

    Returns the raw proof dict on success, None on 404/5xx/network error.
    """
    _ = config  # accepted for API symmetry; not currently used
    url = f"{_rekor_url()}/api/v1/log/entries/{rekor_uuid}/proof"
    try:
        with httpx.Client(timeout=PROOF_TIMEOUT_S) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        log.warning(
            "transparency.sigstore.proof_network_error",
            rekor_uuid=rekor_uuid,
            error=str(exc),
        )
        return None
    if resp.status_code != 200:
        return None
    try:
        out = resp.json()
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def list_pending_submissions(*, config: Config | None = None) -> list[SignedEvent]:
    cfg = config or load_config()
    return [ev for ev in iter_events(config=cfg) if ev.rekor_uuid is None]


def mark_submitted(*, event_id: int, rekor_uuid: str, config: Config | None = None) -> None:
    cfg = config or load_config()
    conn = _connect(cfg)
    try:
        _ensure_schema(conn)
        cur = conn.execute(
            "UPDATE signed_events SET rekor_uuid = ? WHERE id = ? AND rekor_uuid IS NULL",
            (rekor_uuid, event_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"No pending event with id {event_id!r}; already submitted or absent.")
        log.info(
            "transparency.sigstore.submitted",
            event_id=event_id,
            rekor_uuid=rekor_uuid,
        )
    finally:
        conn.close()


def retry_pending_submissions(*, config: Config | None = None) -> int:
    """Iterate pending events, call ``submit_to_rekor``, mark submitted on success.

    Returns the number of events successfully submitted.
    """
    cfg = config or load_config()
    submitted = 0
    for ev in list_pending_submissions(config=cfg):
        rekor_uuid = submit_to_rekor(event_id=ev.id, config=cfg)
        if rekor_uuid is not None:
            mark_submitted(event_id=ev.id, rekor_uuid=rekor_uuid, config=cfg)
            submitted += 1
    return submitted


__all__ = [
    "DEFAULT_REKOR_URL",
    "get_inclusion_proof",
    "list_pending_submissions",
    "mark_submitted",
    "retry_pending_submissions",
    "submit_signed_payload",
    "submit_to_rekor",
]
