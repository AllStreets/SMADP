"""Synchronous in-process dispatcher: match subscriptions, enqueue deliveries.

Called from inside business-logic flows (e.g. after the passport renderer
appends its transparency event). The worker process consumes the rows
asynchronously.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

import structlog

from smadp.config import Config, load_config
from smadp.schemas.webhooks import EventType
from smadp.utils.time import utcnow
from smadp.webhooks import deliveries, store
from smadp.webhooks.envelope import build_envelope, canonical_envelope_bytes

log = structlog.get_logger(__name__)


def _generate_event_id(now: datetime) -> str:
    ts = now.strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"evt_{ts}_{suffix}"


def dispatch_event(
    *,
    event_type: EventType,
    payload: dict[str, Any],
    workspace_id: str,
    signature_meta: dict[str, Any],
    config: Config | None = None,
) -> int:
    """Fan an event out to every matching active subscription.

    Returns the number of delivery rows created (one per matching sub).
    Caller MUST include ``signature_meta["transparency_log_id"]`` (the
    transparency event id from ``journal.append_event(...).id``); the
    envelope schema requires it.
    """
    cfg = config or load_config()
    matches = store.match_subscriptions(
        workspace_id=workspace_id, event_type=event_type, config=cfg
    )
    if not matches:
        log.info(
            "webhooks.dispatch.no_subscribers",
            event_type=event_type.value,
            workspace_id=workspace_id,
        )
        return 0

    now = utcnow()
    event_id = _generate_event_id(now)
    envelope = build_envelope(
        event_id=event_id,
        event_type=event_type,
        created_at=now,
        workspace_id=workspace_id,
        data=payload,
        signature_meta=signature_meta,
    )
    body = canonical_envelope_bytes(envelope)

    enqueued = 0
    for sub in matches:
        deliveries.enqueue(
            subscription_id=sub.id,
            event_id=event_id,
            event_type=event_type,
            body=body,
            config=cfg,
        )
        enqueued += 1

    log.info(
        "webhooks.dispatch.enqueued",
        event_id=event_id,
        event_type=event_type.value,
        workspace_id=workspace_id,
        subscribers=enqueued,
    )
    return enqueued


__all__ = ["dispatch_event"]
